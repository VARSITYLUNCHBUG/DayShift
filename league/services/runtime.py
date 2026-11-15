"""A server's runtime switches (see `league.models.RuntimeSettings`)."""

from __future__ import annotations

from league.models import Community, RuntimeSettings


def of(community: Community | int) -> RuntimeSettings:
    """This server's settings, created with the defaults on first use."""
    community_id = community if isinstance(community, int) else community.pk
    settings, _ = RuntimeSettings.objects.get_or_create(community_id=community_id)
    return settings


def update(community: Community | int, **values: object) -> RuntimeSettings:
    settings = of(community)
    for name, value in values.items():
        setattr(settings, name, value)
    settings.save(update_fields=list(values))
    return settings
