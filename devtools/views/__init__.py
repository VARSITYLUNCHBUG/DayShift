"""The control API's routes, by resource. Importing this package registers all of them."""

from devtools.views import matches, meta, players, queue, scenarios, state, timers

__all__ = ["matches", "meta", "players", "queue", "scenarios", "state", "timers"]
