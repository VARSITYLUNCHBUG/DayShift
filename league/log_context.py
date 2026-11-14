"""Which server, match or draft the code running now belongs to, for routing its logs.

Set with `bind` around a unit of work: an interaction, an effect, a deadline. The error channel
(`bot.error_log`) reads it to post an error only to its own server's channel.

Always use `bind`, never a bare `set`: asgiref's `sync_to_async` copies context changes made in
sync code back into the calling task, so a value left set would leak into whatever runs next.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import Any

_EMPTY: MappingProxyType[str, Any] = MappingProxyType({})
_context: ContextVar[MappingProxyType[str, Any]] = ContextVar("log_context", default=_EMPTY)


def current() -> MappingProxyType[str, Any]:
    """The fields bound now, such as `guild`, `match`, `draft` and `effect`."""
    return _context.get()


@contextmanager
def bind(**fields: Any) -> Iterator[None]:
    """Add fields for the duration of the block. Fields set to None are left out."""
    merged = dict(_context.get())
    merged.update({key: value for key, value in fields.items() if value is not None})
    token = _context.set(MappingProxyType(merged))
    try:
        yield
    finally:
        _context.reset(token)
