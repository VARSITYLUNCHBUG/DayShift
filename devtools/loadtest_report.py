"""Read a load test's bot log and say how close each Discord limit came. Dev only.

    docker logs dayshift-live-bot-1 --since 30m 2>&1 | python devtools/loadtest_report.py

It reads the JSON log lines the bot writes with LOG_FORMAT=json and DISCORD_REQUEST_LOG on (one
"Discord request" line per response; see bot/request_health.py), and reports:

- the busiest second of bot-token requests against Discord's 50 a second (interaction responses
  and webhooks don't count towards it);
- every rate limit (429) by route and scope, and the refused requests Discord counts towards its
  10,000-in-ten-minutes ban (401, 403, and 429s that aren't shared-scope);
- each bucket, kept per channel or guild, by how close it came to running out: its limit, the
  fewest requests it had left, and how often it hit zero;
- requests and latency by route.

Standard library only, so it runs anywhere Python does.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict, deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime

GLOBAL_LIMIT = 50  # Bot-token requests a second.
BAN_LINE = 10_000  # Refused requests in ten minutes.


@dataclass(frozen=True, slots=True)
class Request:
    at: float
    method: str
    route: str
    status: int
    bucket: str | None
    major: str | None
    limit: int | None
    remaining: int | None
    scope: str | None
    ms: int | None

    @property
    def counts_globally(self) -> bool:
        return not self.route.startswith(("/interactions/", "/webhooks/"))

    @property
    def refused(self) -> bool:
        """What Discord counts towards its ban."""
        return self.status in {401, 403} or (self.status == 429 and self.scope != "shared")


def _int(value: object) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def parse(lines: Iterable[str]) -> Iterator[Request]:
    for line in lines:
        start = line.find("{")
        if start < 0:
            continue
        try:
            row = json.loads(line[start:])
        except ValueError:
            continue
        if row.get("msg") != "Discord request":
            continue
        yield Request(
            at=datetime.fromisoformat(row["ts"]).timestamp(),
            method=row.get("method", ""),
            route=row.get("route", ""),
            status=int(row.get("status", 0)),
            bucket=row.get("bucket"),
            major=row.get("major"),
            limit=_int(row.get("limit")),
            remaining=_int(row.get("remaining")),
            scope=row.get("scope"),
            ms=_int(row.get("ms")),
        )


def peak(times: list[float], window: float) -> tuple[int, float]:
    """The most events in any `window` seconds, and when that window started."""
    best, best_at, recent = 0, 0.0, deque[float]()
    for moment in sorted(times):
        recent.append(moment)
        while moment - recent[0] > window:
            recent.popleft()
        if len(recent) > best:
            best, best_at = len(recent), recent[0]
    return best, best_at


def _pct(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _clock(at: float) -> str:
    return datetime.fromtimestamp(at).strftime("%H:%M:%S")


def report(requests: list[Request]) -> str:
    if not requests:
        return (
            "No 'Discord request' lines: run the bot with DISCORD_REQUEST_LOG=1 and "
            "LOG_FORMAT=json."
        )
    out: list[str] = []
    first, last = requests[0].at, requests[-1].at
    span = max(last - first, 1.0)
    bot_token = [r.at for r in requests if r.counts_globally]
    out.append(
        f"{len(requests)} requests from {_clock(first)} to {_clock(last)} ({span:.0f} s), "
        f"{len(bot_token)} on the bot token, {len(bot_token) / span:.1f} a second on average."
    )
    busiest, at = peak(bot_token, 1.0)
    out.append(
        f"Busiest second: {busiest} bot-token requests at {_clock(at)}, "
        f"{100 * busiest / GLOBAL_LIMIT:.0f}% of Discord's {GLOBAL_LIMIT} a second."
    )
    ten, _ = peak(bot_token, 10.0)
    out.append(f"Busiest ten seconds: {ten} ({ten / 10:.1f} a second).")

    refused = [r.at for r in requests if r.refused]
    most_refused, _ = peak(refused, 600.0)
    out.append(
        f"Refused requests Discord counts: {len(refused)}; the most in any ten minutes "
        f"{most_refused} of the {BAN_LINE:,} that would get the IP banned."
    )
    limited = [r for r in requests if r.status == 429]
    out.append(f"Rate limits (429): {len(limited)}")
    for (method, route, scope), count in Counter(
        (r.method, r.route, r.scope or "-") for r in limited
    ).most_common():
        out.append(f"  {count:4d}  {method:6s} {route}  scope={scope}")
    statuses = Counter(r.status for r in requests)
    out.append("Statuses: " + ", ".join(f"{s}: {n}" for s, n in sorted(statuses.items())))

    out.append("")
    out.append("Buckets, closest to running out first (limit, fewest left, times at zero, 429s):")
    buckets: dict[tuple[str, str | None], list[Request]] = defaultdict(list)
    for r in requests:
        if r.bucket:
            buckets[r.bucket, r.major].append(r)
    rows = []
    for (_bucket, major), seen in buckets.items():
        limits = [r.limit for r in seen if r.limit is not None]
        left = [r.remaining for r in seen if r.remaining is not None]
        if not limits or not left:
            continue
        limit, fewest = max(limits), min(left)
        names = sorted({f"{r.method} {r.route}" for r in seen})
        rows.append(
            (
                fewest / limit,
                limit,
                fewest,
                sum(1 for value in left if value == 0),
                sum(1 for r in seen if r.status == 429),
                len(seen),
                major or "-",
                ", ".join(names),
            )
        )
    for _share, limit, fewest, zero, hit, count, major, routes in sorted(rows)[:25]:
        out.append(
            f"  limit {limit:5d}  left {fewest:5d}  zero {zero:4d}  429 {hit:3d}  "
            f"n {count:5d}  {major:>20s}  {routes}"
        )

    out.append("")
    out.append("Routes (requests, p50 and p95 ms):")
    by_route: dict[str, list[Request]] = defaultdict(list)
    for r in requests:
        by_route[f"{r.method} {r.route}"].append(r)
    for name, seen in sorted(by_route.items(), key=lambda item: -len(item[1])):
        times = [r.ms for r in seen if r.ms is not None]
        out.append(
            f"  {len(seen):5d}  p50 {_pct(times, 0.5):5d}  p95 {_pct(times, 0.95):5d}  {name}"
        )
    return "\n".join(out)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    requests: list[Request] = []
    if sys.argv[1:]:
        for path in sys.argv[1:]:
            with open(path, encoding="utf-8") as source:
                requests.extend(parse(source))
    else:
        requests.extend(parse(sys.stdin))
    print(report(sorted(requests, key=lambda request: request.at)))


if __name__ == "__main__":
    main()
