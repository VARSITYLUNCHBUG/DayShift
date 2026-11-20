"""Escalating cooldowns driven by strikes. Automatic for missed ready checks, dodges and leavers.

Each offence adds strikes, recorded on its penalty. The cooldown comes from the kind's ladder,
one rung higher for every strike the player already carries, from any kind of offence. Clean
completed matches and time without an offence work the strikes back off: see `standing`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from league.domain.standing import ladder_rung
from league.models import Community, Match, Penalty, Player
from league.models.moderation import PenaltyKind
from league.services import live, standing
from league.services.common import now


def active_penalty(community: Community, player: Player) -> Penalty | None:
    return (
        Penalty.objects.filter(
            community=community, player=player, revoked_at__isnull=True, expires_at__gt=now()
        )
        .order_by("-expires_at")
        .first()
    )


def ladder(community: Community, kind: str) -> list[int]:
    """A kind's cooldown minutes by rung: rung N is for a player already carrying N strikes, and
    the last rung for that many or more."""
    ladders = standing.policy_of(community).get("ladders", {})
    minutes = ladders.get(kind) if isinstance(ladders, dict) else None
    return [int(rung) for rung in minutes] if minutes else [60]


def ladder_rung_of(community: Community, penalty: Penalty) -> int | None:
    """The rung this cooldown came from, or None when it didn't come from the ladder: a staff
    cooldown, one given its own length, or one whose ladder has changed since."""
    if penalty.kind == PenaltyKind.MANUAL:
        return None
    minutes = ladder(community, penalty.kind)
    rung = penalty.tier - 1
    length = penalty.expires_at - penalty.starts_at
    if not 0 <= rung < len(minutes) or length != timedelta(minutes=minutes[rung]):
        return None
    return rung


def issue(
    community: Community,
    player: Player,
    kind: str,
    *,
    match: Match | None = None,
    reason: str = "",
    issued_by: Player | None = None,
    minutes: int | None = None,
) -> Penalty:
    """Issue a penalty. Without `minutes`, the duration comes from the ladder and strikes."""
    starts_at: datetime = now()
    before = standing.standing(community, player, starts_at).strikes
    rungs = ladder(community, kind)
    rung = ladder_rung(before, len(rungs))
    if minutes is None:
        minutes = rungs[rung]
    penalty = Penalty.objects.create(
        community=community,
        player=player,
        match=match,
        kind=kind,
        tier=rung + 1,
        strikes=standing.strike_policy(community).points_for(kind),
        starts_at=starts_at,
        expires_at=starts_at + timedelta(minutes=minutes),
        reason=reason[:500],
        issued_by=issued_by,
    )
    live.publish(live.player_topic(player.pk))
    return penalty


def revoke_active(community: Community, player: Player, *, keep_strikes: bool = False) -> int:
    """Lift active cooldowns. Unless told otherwise, their strikes go too: a revoke is usually
    staff correcting a mistake."""
    fields: dict[str, object] = {"revoked_at": now()}
    if not keep_strikes:
        fields["strikes_waived"] = True
    revoked = Penalty.objects.filter(
        community=community, player=player, revoked_at__isnull=True, expires_at__gt=now()
    ).update(**fields)
    if revoked:
        live.publish(live.player_topic(player.pk))
    return revoked


def refusal_text(community: Community, player: Player, penalty: Penalty) -> str:
    """Why a player can't queue, and how they get back to a clean record."""
    timestamp = int(penalty.expires_at.timestamp())
    current = standing.standing(community, player)
    text = f"You're on a queue cooldown until <t:{timestamp}:t>."
    if not current.clean:
        text += " " + standing.describe(current, standing.strike_policy(community))
    return text


__all__ = ["PenaltyKind", "active_penalty", "issue", "refusal_text", "revoke_active"]
