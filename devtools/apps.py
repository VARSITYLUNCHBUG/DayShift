from __future__ import annotations

from django.apps import AppConfig


class DevtoolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "devtools"
    verbose_name = "Dev control API"

    def ready(self) -> None:
        # Registers every route, for the HTTP view and the scenario runner alike.
        import devtools.views  # noqa: F401
