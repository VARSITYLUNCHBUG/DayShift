"""A server's runtime switches (see `league.models.RuntimeSettings`)."""

from __future__ import annotations

from league.models import Community, RuntimeSettings


def of(community: Community | int) -> RuntimeSettings:
    """This server's settings, created with the defaults on first use."""
    community_id = community if isinstance(community, int) else community.pk
    settings, _ = RuntimeSettings.objects.get_or_create(community_id=community_id)
    return settings


INTERIM_FIELDS = frozenset({"interim_points", "interim_start_points", "interim_k_factor"})


def after_change(settings: RuntimeSettings, changed: set[str] | frozenset[str]) -> None:
    """Follow up a settings save made outside a service (the admin): rebuild the interim points
    when they're affected, and redraw the queue panel, which shows capacity and the mode."""
    from league.services import common, interim

    if not changed:
        return
    community = Community.objects.get(pk=settings.community_id)
    if changed & INTERIM_FIELDS:
        interim.set_enabled(community, settings.interim_points)
    common.render_queue(community)


def update(community: Community | int, **values: object) -> RuntimeSettings:
    settings = of(community)
    for name, value in values.items():
        setattr(settings, name, value)
    settings.save(update_fields=list(values))
    return settings
