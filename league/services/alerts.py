"""Staff alerts: one card per thing staff should look at, in the staff channel.

Every alert names an area. Its card pings the roles holding that area and carries its buttons:
a dispute's ruling, or Dismiss for anything else. The card is edited when the alert closes, so
the channel shows what's still open.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from league.domain.errors import NotAllowed, StaleAction
from league.models import Community, Match, Player
from league.models.alerts import AlertKind, AlertStatus, StaffAlert
from league.models.matches import ResourceKind
from league.models.permissions import Area
from league.services import effects, permissions
from league.services.common import add_effect, now

POST_KIND = "post_staff_alert"
REFRESH_KIND = "refresh_staff_alert"
# The match channel also gets a short notice for these, while its players are still there.
MATCH_NOTICE_KINDS = frozenset({AlertKind.DISPUTE, AlertKind.EARLY_LEAVE})


def _lane(community: Community, match: Match | None) -> str | None:
    """Match alerts run in the match's lane, after its other effects; the rest share one."""
    return None if match is not None else f"staff_alerts:{community.pk}"


def _post(alert: StaffAlert, *, reping: bool = False) -> None:
    add_effect(
        alert.community,
        POST_KIND,
        {"alert_id": alert.pk, "reping": reping},
        match=alert.match,
        lane=_lane(alert.community, alert.match),
    )


def _refresh(alert: StaffAlert) -> None:
    add_effect(
        alert.community,
        REFRESH_KIND,
        {"alert_id": alert.pk},
        match=alert.match,
        lane=_lane(alert.community, alert.match),
    )


def raise_alert(
    community: Community,
    kind: AlertKind,
    area: Area,
    text: str,
    *,
    match: Match | None = None,
    dedupe_key: str | None = None,
) -> StaffAlert | None:
    """Open an alert and post its card. A repeat of an open dispute pings it again instead, and
    a dedupe key already used raises nothing. Returns the alert, or None for a duplicate."""
    if kind == AlertKind.DISPUTE and match is not None:
        open_dispute = StaffAlert.objects.filter(
            match=match, kind=AlertKind.DISPUTE, status=AlertStatus.OPEN
        ).first()
        if open_dispute is not None:
            reping(open_dispute)
            return open_dispute
    if dedupe_key is not None and StaffAlert.objects.filter(dedupe_key=dedupe_key).exists():
        return None
    alert = StaffAlert.objects.create(
        community=community,
        match=match,
        kind=kind,
        area=area,
        text=text,
        dedupe_key=dedupe_key,
        created_at=now(),
    )
    _post(alert)
    return alert


def reping(alert: StaffAlert) -> None:
    """Post the card again at the bottom of the channel, pinging its roles once more."""
    if alert.status == AlertStatus.OPEN:
        _post(alert, reping=True)


def reping_dispute(match: Match) -> None:
    alert = StaffAlert.objects.filter(
        match=match, kind=AlertKind.DISPUTE, status=AlertStatus.OPEN
    ).first()
    if alert is not None:
        reping(alert)


def _close(alert: StaffAlert, status: AlertStatus, actor: Player | None, outcome: str) -> None:
    alert.status = status
    alert.closed_at = now()
    alert.closed_by = actor
    alert.outcome = outcome[:200]
    alert.save(update_fields=["status", "closed_at", "closed_by", "outcome"])
    _refresh(alert)


def settle_for_match(
    match: Match, kinds: tuple[AlertKind, ...], actor: Player | None, outcome: str
) -> None:
    """The match moved on in a way that answers these alerts: a ruling, or a void."""
    for alert in StaffAlert.objects.filter(match=match, kind__in=kinds, status=AlertStatus.OPEN):
        _close(alert, AlertStatus.RESOLVED, actor, outcome)


@transaction.atomic
def dismiss(alert_id: int, actor: Player) -> StaffAlert:
    """Mark something dealt with. A dispute can't be dismissed: it needs a ruling."""
    alert = StaffAlert.objects.select_for_update().select_related("community").get(pk=alert_id)
    if alert.status != AlertStatus.OPEN:
        raise StaleAction("That alert is already closed.")
    if alert.kind == AlertKind.DISPUTE:
        raise NotAllowed("A dispute needs a ruling: choose the winner or void it.")
    _close(alert, AlertStatus.DISMISSED, actor, "Dismissed")
    return alert


def area_of(alert_id: int) -> tuple[Community, Area]:
    alert = StaffAlert.objects.select_related("community").get(pk=alert_id)
    return alert.community, Area(alert.area)


@dataclass(frozen=True, slots=True)
class AlertCard:
    """What a card shows, read in one go for the renderer."""

    alert_id: int
    kind: AlertKind
    area: Area
    text: str
    status: AlertStatus
    match_id: int | None
    match_channel_id: int | None
    created_at: datetime
    closed_by: str
    closed_at: datetime | None
    outcome: str
    team_names: tuple[str, str]
    ping_role_ids: tuple[int, ...]


def card(alert_id: int) -> AlertCard:
    from league.services.boards import captain_names, team_name  # boards imports this module.

    alert = StaffAlert.objects.select_related("closed_by", "match").get(pk=alert_id)
    names = ("Team A", "Team B")
    channel_id = None
    if alert.match is not None:
        captains = captain_names(alert.match)
        names = (
            team_name(captains["A"]) if "A" in captains else "Team A",
            team_name(captains["B"]) if "B" in captains else "Team B",
        )
        channel_id = effects.resource_id(alert.match.pk, ResourceKind.TEXT)
    is_open = alert.status == AlertStatus.OPEN
    return AlertCard(
        alert_id=alert.pk,
        kind=AlertKind(alert.kind),
        area=Area(alert.area),
        text=alert.text,
        status=AlertStatus(alert.status),
        match_id=alert.match_id,
        match_channel_id=channel_id,
        created_at=alert.created_at,
        closed_by=alert.closed_by.display_name if alert.closed_by else "",
        closed_at=alert.closed_at,
        outcome=alert.outcome,
        team_names=names,
        ping_role_ids=tuple(permissions.role_ids_with(alert.community_id, [Area(alert.area)]))
        if is_open
        else (),
    )


def where_to_post(alert_id: int) -> tuple[int | None, int | None, int | None]:
    """(channel to post in, the card's current channel, its current message). The staff channel,
    or the match channel on a server whose staff channel isn't set up yet."""
    alert = StaffAlert.objects.select_related("community").get(pk=alert_id)
    target = alert.community.staff_channel_id
    if target is None and alert.match_id is not None:
        target = effects.resource_id(alert.match_id, ResourceKind.TEXT)
    return target, alert.channel_id, alert.message_id


def record_card(alert_id: int, channel_id: int, message_id: int) -> None:
    StaffAlert.objects.filter(pk=alert_id).update(channel_id=channel_id, message_id=message_id)
