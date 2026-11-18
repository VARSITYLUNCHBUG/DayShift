import { Button, Chip, Dropdown, Label } from "@heroui/react";
import { useState } from "react";

import { control, type AdvanceResult, type Match, type MatchPlayer, type Via } from "../../api";
import { Panel } from "../../components/Panel";
import type { Run } from "../../hooks/useAction";
import { actionLabel, validActions } from "../../lib/actions";
import { TERMINAL, formatSeconds, laterStatuses, secondsUntil, statusColor, statusLabel } from "../../lib/match";
import { ActModal } from "./ActModal";
import { ScriptModal } from "./ScriptModal";

function TeamColumn({ title, players, turnIds, checkIn }: { title: string; players: MatchPlayer[]; turnIds: number[]; checkIn: boolean }) {
  return (
    <div className="min-w-0 flex-1">
      <h4 className="mb-1 text-xs font-semibold text-muted">{title}</h4>
      <ul className="flex flex-col gap-0.5">
        {players.map((p) => (
          <li
            key={p.id}
            className={`flex items-center gap-1 truncate ${p.active ? "" : "line-through opacity-60"} ${
              turnIds.includes(p.id) ? "text-accent" : ""
            }`}
            title={p.removedReason ?? undefined}
          >
            {p.isCaptain ? <span aria-label="captain" title="captain">★</span> : null}
            <span className="truncate">{p.name}</span>
            {turnIds.includes(p.id) ? <span className="sr-only">(to act)</span> : null}
            {p.ready ? <span className="text-success" aria-label="ready" title="ready">✓</span> : null}
            {p.missedCheckin ? <span className="text-xs text-warning">missed check-in</span> : null}
            {checkIn && p.isCaptain ? (
              <Chip size="sm" variant="soft" color={p.checkedIn ? "success" : "warning"}>
                {p.checkedIn ? "here" : "not checked in"}
              </Chip>
            ) : null}
          </li>
        ))}
        {players.length === 0 ? <li className="text-muted">—</li> : null}
      </ul>
    </div>
  );
}

function pickColor(action: string, team: "A" | "B" | null) {
  if (action === "ban") return "danger" as const;
  return team === "A" ? ("accent" as const) : ("default" as const);
}

const advanced = (r: AdvanceResult) => `${statusLabel(r.from ?? "?")} → ${statusLabel(r.to ?? "?")} (${r.actions} actions)`;

/** One live match: who is where, what it waits for, its timer, and the autopilot controls. */
export function MatchCard({ match, now, run, via }: { match: Match; now: number; run: Run; via: Via }) {
  const [modal, setModal] = useState<"act" | "script" | null>(null);
  const left = match.frozen ? match.secondsLeft : (secondsUntil(match.deadlineAt, now) ?? match.secondsLeft);
  const later = laterStatuses(match.status);
  const live = !TERMINAL.has(match.status);
  const turnIds = match.turn?.playerIds ?? [];
  const byTeam = (team: "A" | "B" | null) => match.players.filter((p) => p.team === team);
  const undrafted = byTeam(null);
  const checkIn = match.status === "captain_checkin";
  const nextAction = validActions(match).find((c) => c.onTurn);
  const pendingSwap = match.swaps.find((s) => s.status === "pending");

  return (
    <Panel
      className="w-full 2xl:w-[calc(50%-0.5rem)]"
      title={
        <span className="flex flex-wrap items-center gap-2">
          <span className="mono">#{match.id}</span>
          <Chip size="sm" color={statusColor(match.status)} variant="soft">{statusLabel(match.status)}</Chip>
          {match.kind !== "ranked" ? <Chip size="sm">{match.kind}</Chip> : null}
          {match.stepIndex !== null ? <span className="text-muted">step {match.stepIndex}</span> : null}
          {match.mode ? <span className="text-xs text-muted">{match.mode}</span> : null}
        </span>
      }
      actions={
        <span className="flex items-center gap-2">
          {match.frozen ? <Chip size="sm" color="warning" variant="soft">frozen</Chip> : null}
          {match.onHold ? <Chip size="sm" color="warning" variant="soft">on hold (sub)</Chip> : null}
          <span
            className={`mono text-base ${left !== null && left <= 10 ? "text-danger" : ""}`}
            aria-label={left === null ? "no timer" : `time left ${formatSeconds(left)}`}
          >
            {left === null ? "no timer" : formatSeconds(left)}
          </span>
        </span>
      }
    >
      <div className="flex flex-col gap-3">
        {match.turn ? (
          <p>
            Waiting for <strong>{nextAction ? nextAction.label.toLowerCase() : match.turn.action}</strong>
            {match.turn.team ? <span> by team {match.turn.team}</span> : null}
            {match.turn.names.length ? (
              <span className="text-muted">
                {" "}
                · {match.turn.names.slice(0, 6).join(", ")}
                {match.turn.names.length > 6 ? ` +${match.turn.names.length - 6}` : ""}
              </span>
            ) : null}
          </p>
        ) : null}
        <div className="flex gap-4">
          <TeamColumn title="Team A" players={byTeam("A")} turnIds={turnIds} checkIn={checkIn} />
          <TeamColumn title="Team B" players={byTeam("B")} turnIds={turnIds} checkIn={checkIn} />
          {undrafted.length ? <TeamColumn title="Undrafted" players={undrafted} turnIds={turnIds} checkIn={checkIn} /> : null}
        </div>
        {match.votes.length ? (
          <p className="text-muted">votes: {match.votes.map((v) => `${v.name} ${v.count}`).join(", ")}</p>
        ) : null}
        {match.picks.length ? (
          <ul className="flex flex-wrap gap-1" aria-label="Picks and bans">
            {match.picks.map((p, i) => (
              <li key={`${p.step ?? i}-${p.label}`}>
                <Chip size="sm" variant="soft" color={pickColor(p.action, p.team)}>
                  {p.step !== null ? `${p.step} ` : ""}
                  {p.team ?? ""} {p.action === "player_pick" ? "drafts" : p.action} {p.label}
                  {p.source && p.source !== "user" ? ` (${p.source})` : ""}
                </Chip>
              </li>
            ))}
          </ul>
        ) : null}
        {pendingSwap ? (
          <p className="text-warning">swap offered: {pendingSwap.label}, waiting for the other captain</p>
        ) : null}
        {match.swaps.some((s) => s.status !== "pending") ? (
          <p className="text-xs text-muted">
            swaps: {match.swaps.filter((s) => s.status !== "pending").map((s) => `${s.label} ${s.status}`).join(" · ")}
          </p>
        ) : null}
        {match.subRequests.length ? (
          <p className="text-warning">
            {match.subRequests.map((s) => `sub #${s.id} ${s.status}: ${s.leaving ?? "?"} leaving, ${s.offers} offers`).join(" · ")}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-x-4 text-muted">
          {match.coinflipWinner ? <span>coinflip: team {match.coinflipWinner}</span> : null}
          {match.apiLobby?.partyId ? (
            <span>
              deadlock-api party <span className="mono">{match.apiLobby.partyId}</span>
              {match.apiLobby.started ? ", started" : ", not started"}
            </span>
          ) : null}
          {match.apiLobby?.failed ? <span className="text-warning">deadlock-api refused: code by hand</span> : null}
          {match.lobbyCode ? <span>lobby code: <span className="mono">{match.lobbyCode}</span></span> : null}
          {match.winner ? <span>winner: team {match.winner}</span> : null}
          {match.textChannelId ? <span>channel: <span className="mono">{match.textChannelId}</span></span> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            isDisabled={!live}
            onPress={() => void run("Complete phase", () => control.advance(match.id, { via }), advanced)}
          >
            Complete phase
          </Button>
          <Dropdown>
            <Button size="sm" variant="secondary" isDisabled={!live || later.length === 0}>
              Advance to ▸
            </Button>
            <Dropdown.Popover>
              <Dropdown.Menu
                aria-label="Advance to status"
                onAction={(key) =>
                  void run(`Advance to ${String(key)}`, () => control.advance(match.id, { until: String(key), via }), advanced)
                }
              >
                {later.map((s) => (
                  <Dropdown.Item key={s} id={s} textValue={statusLabel(s)}>
                    <Label>{statusLabel(s)}</Label>
                  </Dropdown.Item>
                ))}
              </Dropdown.Menu>
            </Dropdown.Popover>
          </Dropdown>
          {match.frozen ? (
            <Button size="sm" variant="secondary" onPress={() => void run("Resume", () => control.resume(match.id))}>
              Resume timer
            </Button>
          ) : (
            <Button size="sm" variant="secondary" isDisabled={!live} onPress={() => void run("Pause", () => control.pause(match.id))}>
              Pause timer
            </Button>
          )}
          <Button size="sm" variant="secondary" isDisabled={!live} onPress={() => void run("Fire deadline", () => control.fire(match.id))}>
            Fire now
          </Button>
          <Button size="sm" variant="tertiary" isDisabled={!live} onPress={() => { setModal("act"); }}>
            {nextAction ? `Act as… (${actionLabel(nextAction.action).toLowerCase()})` : "Act as…"}
          </Button>
          <Button size="sm" variant="tertiary" onPress={() => { setModal("script"); }}>
            Script…
          </Button>
        </div>
      </div>
      {modal === "act" ? <ActModal match={match} run={run} via={via} onClose={() => { setModal(null); }} /> : null}
      {modal === "script" ? <ScriptModal match={match} run={run} onClose={() => { setModal(null); }} /> : null}
    </Panel>
  );
}
