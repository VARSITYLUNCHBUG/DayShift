from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Q

from league.domain.engine import Status
from league.integrations import deadlock_api
from league.models import Match
from league.services import postgame

FINISHED = (Status.AWAITING_CONFIRMATION, Status.DISPUTED, Status.COMPLETED)


class Command(BaseCommand):
    help = (
        "Build the web's postgame data for finished matches. Only a summary of deadlock-api's "
        "match data is kept, so this fetches each match's metadata from deadlock-api again: one "
        "request per match, and without an API key the rate limit is tight. With no --match, "
        "it builds every finished match with a Deadlock ID that has no postgame in the current "
        "schema yet."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--match", type=int, action="append", dest="matches", help="A match ID; repeatable."
        )
        parser.add_argument(
            "--metadata-file",
            type=Path,
            help=(
                "Build from this deadlock-api metadata file (JSON, or .json.gz) instead of "
                "fetching it, for one --match. For local testing and replays."
            ),
        )

    def _metadata(self, path: Path) -> dict[str, Any]:
        raw = path.read_bytes()
        if path.suffix == ".gz":
            raw = gzip.decompress(raw)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise CommandError(f"{path} isn't a deadlock-api metadata object.")
        return data

    def handle(self, *args: Any, **options: Any) -> None:
        ids: list[int] | None = options.get("matches")
        metadata_file: Path | None = options.get("metadata_file")
        if metadata_file is not None and (not ids or len(ids) != 1):
            raise CommandError("--metadata-file builds one match: give exactly one --match.")
        metadata = self._metadata(metadata_file) if metadata_file is not None else None
        matches = Match.objects.exclude(deadlock_match_id=None).select_related("community")
        if ids:
            matches = matches.filter(pk__in=ids)
            missing = set(ids) - set(matches.values_list("pk", flat=True))
            if missing:
                raise CommandError(
                    "No Deadlock match ID for match(es) " + ", ".join(map(str, sorted(missing)))
                )
        else:
            matches = matches.filter(status__in=FINISHED).exclude(
                Q(postgame__isnull=False) & Q(postgame__schema_version=postgame.SCHEMA_VERSION)
            )
        built = absent = failed = 0
        for match in matches.order_by("pk"):
            try:
                row = postgame.build(match, metadata)
            except deadlock_api.ApiError as exc:
                failed += 1
                self.stdout.write(f"Match {match.pk}: {exc}")
                if exc.rate_limited:
                    self.stdout.write("Rate limited by deadlock-api: stopping. Run it again later.")
                    break
                continue
            except ValueError as exc:
                failed += 1
                self.stdout.write(f"Match {match.pk}: {exc}")
                continue
            if row is None:
                absent += 1
                self.stdout.write(f"Match {match.pk}: deadlock-api has no data for it.")
            else:
                built += 1
        self.stdout.write(
            f"Postgames: {built} built, {absent} with no data on deadlock-api, {failed} failed."
        )
