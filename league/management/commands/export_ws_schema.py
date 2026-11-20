"""Write the websocket protocol, the actions' arguments and the HTTP API's responses as one JSON
Schema, which the web UI's TypeScript types are generated from (`npm run gen` in services/web)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from pydantic import BaseModel

from league.web.live.actions import ActionArgs
from league.web.live.schema import protocol_schema

DEFAULT_OUT = Path("services") / "web" / "src" / "live" / "protocol.schema.json"


def http_api() -> type[BaseModel] | None:
    """The HTTP API's responses (`league.web.api.schema.HttpApi`), once that module has them."""
    try:
        module = importlib.import_module("league.web.api.schema")
    except ImportError:
        return None
    model = getattr(module, "HttpApi", None)
    return model if isinstance(model, type) and issubclass(model, BaseModel) else None


def render() -> str:
    """The schema file's text. A test compares it with the checked-in copy."""
    document = protocol_schema(http=http_api(), actions=ActionArgs)
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = (
        "Write the websocket protocol and the HTTP API's responses as JSON Schema, for the "
        "web UI's generated types."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--out", type=Path, default=None, help=f"Where to write it. Default: {DEFAULT_OUT}"
        )

    def handle(self, *args: Any, **options: Any) -> None:
        out: Path = options["out"] or settings.BASE_DIR / DEFAULT_OUT
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(), encoding="utf-8", newline="\n")
        self.stdout.write(f"Wrote {out}.")
