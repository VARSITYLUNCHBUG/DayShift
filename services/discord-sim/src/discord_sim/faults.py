"""Injected REST failures, to exercise the bot's retry and error paths (POST /_sim/faults)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from discord_sim.errors import ControlError


@dataclass
class Fault:
    id: int
    path: str  # A regular expression searched in the request path.
    method: str | None
    status: int
    code: int
    message: str
    retry_after: float
    times: int  # How many more requests it hits. -1: until removed.
    pattern: re.Pattern[str] = field(repr=False)

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "method": self.method,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "retry_after": self.retry_after,
            "times": self.times,
        }

    def body(self) -> dict[str, Any]:
        if self.status == 429:
            return {
                "message": "You are being rate limited.",
                "retry_after": self.retry_after,
                "global": False,
                "code": self.code,
            }
        return {"message": self.message, "code": self.code}


class Faults:
    def __init__(self) -> None:
        self._faults: list[Fault] = []
        self._next_id = 1

    def add(self, spec: dict[str, Any]) -> Fault:
        try:
            status = int(spec["status"])
            pattern = re.compile(str(spec["path"]))
        except (KeyError, ValueError, re.error) as exc:
            raise ControlError(400, f"A fault needs a path regex and a status: {exc}") from None
        method = spec.get("method")
        fault = Fault(
            id=self._next_id,
            path=pattern.pattern,
            method=str(method).upper() if method else None,
            status=status,
            code=int(spec.get("code", 0)),
            message=str(spec.get("message") or f"Injected {status}"),
            retry_after=float(spec.get("retry_after", 1.0)),
            times=int(spec.get("times", 1)),
            pattern=pattern,
        )
        self._next_id += 1
        self._faults.append(fault)
        return fault

    def match(self, method: str, path: str) -> Fault | None:
        for fault in self._faults:
            if fault.method not in (None, method) or not fault.pattern.search(path):
                continue
            if fault.times > 0:
                fault.times -= 1
                if fault.times == 0:
                    self._faults.remove(fault)
            return fault
        return None

    def all(self) -> list[Fault]:
        return list(self._faults)

    def clear(self) -> None:
        self._faults.clear()
