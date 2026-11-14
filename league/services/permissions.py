"""Which roles hold which staff areas. The Discord layer works out a member's roles; this only
stores and reads grants, so it knows nothing about owners or Administrators."""

from __future__ import annotations

from collections.abc import Collection, Iterable

from league.models.permissions import Area, CommunityRoleGrant

ALL_AREAS: frozenset[Area] = frozenset(Area)
# Staff who look after matches see every match channel and the scoreboard archive.
MATCH_STAFF_AREAS: tuple[Area, ...] = (Area.MATCH_CONTROL, Area.DISPUTES, Area.RATINGS)


def areas_for_roles(community_id: int, role_ids: Iterable[int]) -> frozenset[Area]:
    ids = list(role_ids)
    if not ids:
        return frozenset()
    rows = CommunityRoleGrant.objects.filter(community_id=community_id, role_id__in=ids)
    return frozenset(Area(area) for area in rows.values_list("area", flat=True))


def role_ids_with(community_id: int, areas: Collection[Area]) -> list[int]:
    """The roles holding any of these areas, in a stable order."""
    rows = CommunityRoleGrant.objects.filter(community_id=community_id, area__in=list(areas))
    return sorted(set(rows.values_list("role_id", flat=True)))


def grant(
    community_id: int, role_id: int, areas: Collection[Area], granted_by: int | None
) -> list[Area]:
    """Grant the areas the role doesn't hold yet. Returns those newly granted."""
    held = set(
        CommunityRoleGrant.objects.filter(community_id=community_id, role_id=role_id).values_list(
            "area", flat=True
        )
    )
    new = [area for area in Area if area in areas and area not in held]
    CommunityRoleGrant.objects.bulk_create(
        [
            CommunityRoleGrant(
                community_id=community_id,
                role_id=role_id,
                area=area,
                granted_by_discord_id=granted_by,
            )
            for area in new
        ],
        ignore_conflicts=True,  # A concurrent grant of the same area is the same outcome.
    )
    return new


def revoke(community_id: int, role_id: int, areas: Collection[Area]) -> list[Area]:
    """Revoke the areas the role holds. Returns those it held."""
    rows = CommunityRoleGrant.objects.filter(
        community_id=community_id, role_id=role_id, area__in=list(areas)
    )
    held = [Area(area) for area in rows.values_list("area", flat=True)]
    rows.delete()
    return [area for area in Area if area in held]


def grants_by_area(community_id: int) -> dict[Area, list[int]]:
    """Every area, with the roles that hold it (possibly none)."""
    found: dict[Area, list[int]] = {area: [] for area in Area}
    rows = CommunityRoleGrant.objects.filter(community_id=community_id).order_by("role_id")
    for area, role_id in rows.values_list("area", "role_id"):
        found[Area(area)].append(role_id)
    return found
