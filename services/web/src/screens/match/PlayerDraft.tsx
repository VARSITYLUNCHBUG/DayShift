// The player draft (B05, B06): the pick order, the players still to pick, both teams filling up.
// The captain on the clock picks with one press; everyone else watches. The lobby chat is in the
// rail.
import { useState } from "react";

import { PlayerGrid } from "../../components/PlayerGrid";
import { TeamPanel } from "../../components/TeamPanel";
import { TEAM_CLASS } from "../../components/team";
import { notify } from "../../components/toast";
import { cn } from "../../lib/cn";
import { number } from "../../lib/format";
import type { MatchSnap, Team } from "../../live/protocol.gen";
import { useMatchAction } from "../../match/live";
import { leftRight, nameOf, playerDraftLine, playerPool, playerTimeoutPick, teamKey, teamPlayers, turnTitle } from "../../match/model";
import { Note, StageHead } from "./Parts";
import { Room, useMe } from "./Room";
import type { MatchScreenProps } from "./types";

export function PlayerDraft({ match }: MatchScreenProps) {
  const { myId } = useMe(match);
  const act = useMatchAction();
  const [picking, setPicking] = useState<string | null>(null);
  const turn = match.turn;
  const acting = match.viewer.is_acting && turn?.action === "player_pick";
  const tone = turn ? teamKey(match, turn.team) : null;
  const pool = playerPool(match);
  const pickingName = pool.find((p) => p.id === picking)?.name;

  const pick = (playerId: string) => {
    if (!acting || act.pending) return;
    setPicking(playerId);
    act
      .run("draft.pick_player", { match_id: match.id, step_index: match.step_index, player_id: playerId })
      .catch(notify.error)
      .finally(() => setPicking(null));
  };

  const first = match.player_draft_order[0]?.team ?? "A";
  const eyebrows: Partial<Record<Team, string>> = { [first]: "Picks players first", [first === "A" ? "B" : "A"]: "Picks second" };

  return (
    <Room
      match={match}
      acting={turn?.team ?? null}
      eyebrows={eyebrows}
      phaseLine={acting ? "Players · your pick" : "Players"}
      now={{
        title: turnTitle(match),
        line: playerDraftLine(match),
        tone,
        deadline: match.deadline_at,
        announce: acting ? "to pick" : undefined,
      }}
      rail={
        <Note title="Sides come later">
          The coinflip after the draft decides which side each team plays. The Hidden King always bans and picks heroes first.
        </Note>
      }
    >
      <PickOrder match={match} />
      <StageHead
        eyebrow={acting ? "Your pick" : turn ? `${turn.captain_name} is picking` : "Player draft"}
        title={acting ? "Pick a player" : "The captains are picking"}
        lead={
          acting
            ? pickingName
              ? `Picking ${pickingName}…`
              : `Press a player to pick them. No pick in time and you get ${playerTimeoutPick(match)}.`
            : match.viewer.is_player && match.viewer.team === null
              ? "You're still to be picked. The lobby chat is open until the teams are set."
              : undefined
        }
        tone={tone ? TEAM_CLASS[tone].text : undefined}
      />
      <PlayerGrid
        aria-label={acting ? "Players left: press one to pick" : "Players left"}
        players={pool.map((p) => ({
          id: p.id,
          name: p.name,
          avatar: p.avatar_url,
          isYou: p.id === myId,
          line: p.rating > 0 ? `${number(p.rating)} rating` : undefined,
          isTaken: picking !== null && picking !== p.id,
        }))}
        selectedId={picking}
        onSelect={acting ? pick : undefined}
      />
      <div className="flex flex-wrap gap-4">
        {leftRight(match).map((team) => (
          <DraftTeam key={team} match={match} team={team} myId={myId} />
        ))}
      </div>
    </Room>
  );
}

function DraftTeam({ match, team, myId }: { match: MatchSnap; team: Team; myId: string | null }) {
  const players = teamPlayers(match, team);
  const slots = match.player_draft_order.filter((s) => s.team === team).length + 1;
  const open = Math.max(0, slots - players.length);
  const key = teamKey(match, team);
  return (
    <div className="flex min-w-0 flex-1 basis-75 flex-col gap-2">
      <TeamPanel
        team={key}
        name={nameOf(match, team)}
        line={match.viewer.team === team ? "Yours" : `${match.captains[team] ?? "Their captain"} picks`}
        players={[
          ...players.map((p) => ({
            id: p.id,
            name: p.name,
            avatar: p.avatar_url,
            isYou: p.id === myId,
            line: p.is_captain ? "Captain" : p.rating > 0 ? `${number(p.rating)} rating` : undefined,
          })),
        ]}
        className={cn(match.turn?.team === team && TEAM_CLASS[key].border)}
      />
      {open > 0 ? (
        <p className="px-4 text-caption text-muted">
          {open} {open === 1 ? "place" : "places"} open
        </p>
      ) : null}
    </div>
  );
}

/** The pick order strip: who picks each place, done ones with the player taken. */
function PickOrder({ match }: { match: MatchSnap }) {
  const done = match.draft.filter((d) => d.action === "player_pick");
  return (
    <ol aria-label="Pick order" className="grid grid-cols-5 gap-1 sm:grid-cols-10">
      {match.player_draft_order.map((step, index) => {
        const entry = done[index];
        const now = !entry && index === done.length && match.turn !== null;
        const key = teamKey(match, step.team);
        const captain = match.captains[step.team] ?? nameOf(match, step.team);
        return (
          <li
            key={step.step_index}
            aria-current={now ? "step" : undefined}
            aria-label={`Pick ${index + 1}, ${captain}${entry ? `: ${entry.label}${entry.random ? " (random)" : ""}` : now ? ", now" : ""}`}
            className={cn(
              "flex h-10 items-center justify-center truncate rounded-small border px-1 text-micro font-extrabold",
              now
                ? TEAM_CLASS[key].fill
                : entry
                  ? "border-line bg-background text-faint"
                  : cn(TEAM_CLASS[key].soft, TEAM_CLASS[key].light, TEAM_CLASS[key].softBorder),
            )}
          >
            <span aria-hidden="true" className="truncate">
              {entry ? entry.label : captain}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
