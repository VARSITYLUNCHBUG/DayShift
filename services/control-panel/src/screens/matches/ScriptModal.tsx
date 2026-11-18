import { Button, Modal } from "@heroui/react";
import { useState, type ReactNode } from "react";

import { COINFLIP_CHOICES, control, type Match, type MatchScript } from "../../api";
import { AreaField, Field } from "../../components/Field";
import { SimpleSelect } from "../../components/SimpleSelect";
import { describeError, type Run } from "../../hooks/useAction";
import { parseChampionLines, parseList, statusLabel } from "../../lib/match";

function championLines(script: Record<string, unknown>): string {
  const steps = Array.isArray(script.champions) ? (script.champions as Record<string, unknown>[]) : [];
  return steps
    .map((s) => [s.step, s.slug ?? s.champion, s.team].filter((v) => v !== undefined && v !== null).map(String).join(" "))
    .join("\n");
}

function Phase({ status, current, children }: { status: string; current: string; children: ReactNode }) {
  return (
    <fieldset className={`flex flex-col gap-2 rounded-md border p-3 ${status === current ? "border-accent" : "border-separator"}`}>
      <legend className="px-1 text-xs font-semibold text-muted">
        {statusLabel(status)}
        {status === current ? " (now)" : ""}
      </legend>
      {children}
    </fieldset>
  );
}

/** The plan the autopilot follows for one match, phase by phase. */
export function ScriptModal({ match, run, onClose }: { match: Match; run: Run; onClose: () => void }) {
  const script = match.script;
  const [draft, setDraft] = useState(Array.isArray(script.draft) ? script.draft.join(", ") : "");
  const [champions, setChampions] = useState(championLines(script));
  const [votes, setVotes] = useState(script.captain_votes ? JSON.stringify(script.captain_votes) : "");
  const [coinflip, setCoinflip] = useState(typeof script.coinflip === "string" ? script.coinflip : "");
  const [lobbyCode, setLobbyCode] = useState(typeof script.lobby_code === "string" ? script.lobby_code : "");
  const [winner, setWinner] = useState(typeof script.winner === "string" ? script.winner : "");
  const [error, setError] = useState<string | null>(null);
  const undrafted = match.players.filter((p) => p.active && !p.isCaptain);
  const now = match.status;

  const addToDraft = (id: number) => {
    const order = parseList(draft);
    if (!order.includes(String(id))) setDraft([...order, String(id)].join(", "));
  };

  const save = async () => {
    // Every key devtools' clean_script takes has a field here, and it refuses any other.
    const body: MatchScript = {};
    try {
      if (votes.trim()) body.captain_votes = JSON.parse(votes) as Record<string, number[]>;
    } catch (err) {
      setError(`Not JSON: ${describeError(err)}`);
      return;
    }
    const order = parseList(draft).map(Number).filter(Number.isFinite);
    if (order.length) body.draft = order;
    const steps = parseChampionLines(champions);
    if (steps.length) body.champions = steps;
    if (coinflip) body.coinflip = coinflip;
    if (lobbyCode.trim()) body.lobby_code = lobbyCode.trim();
    if (winner === "A" || winner === "B") body.winner = winner;
    setError(null);
    const out = await run("Save script", () => control.setScript(match.id, body));
    if (out !== undefined) onClose();
  };

  return (
    <Modal.Backdrop isOpen onOpenChange={(open) => { if (!open) onClose(); }}>
      <Modal.Container size="lg" scroll="inside">
        <Modal.Dialog>
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Heading>Script for match #{match.id}</Modal.Heading>
          </Modal.Header>
          <Modal.Body className="flex flex-col gap-3">
            <p className="text-muted">
              Complete phase and Advance follow this plan before their defaults. Every field is
              optional, empty means the default, and saving replaces the whole script.
            </p>
            <Phase status="captain_phase" current={now}>
              <Field
                label='Captain votes (JSON: voter id or "*" to the 1 or 2 candidates)'
                value={votes}
                onChange={setVotes}
                placeholder='{"*": [1, 4]}'
              />
            </Phase>
            <Phase status="captain_checkin" current={now}>
              <p className="text-xs text-muted">
                Both captains check in. To test a missed check-in, fire the deadline instead.
              </p>
            </Phase>
            <Phase status="player_draft" current={now}>
              <Field label="Draft order (player ids, in the order captains pick them)" value={draft} onChange={setDraft} placeholder="highest skill first" />
              <div className="flex flex-wrap gap-1" role="group" aria-label="Add a player to the draft order">
                {undrafted.map((p) => (
                  <Button key={p.id} size="sm" variant="ghost" onPress={() => { addToDraft(p.id); }}>
                    + {p.name} <span className="mono text-muted">{p.id}</span>
                  </Button>
                ))}
              </div>
            </Phase>
            <Phase status="coinflip" current={now}>
              <SimpleSelect
                className="w-56"
                label="The winner's side"
                value={coinflip}
                onChange={setCoinflip}
                options={[{ id: "", label: "default (hidden_king)" }, ...COINFLIP_CHOICES.map((c) => ({ id: c, label: c }))]}
              />
              <p className="text-xs text-muted">Swaps after the draft: use Act as… (Offer a player swap) while the coinflip, champion draft or lobby runs.</p>
            </Phase>
            <Phase status="champion_draft" current={now}>
              <AreaField
                label="Champion steps (one per line: step slug [team])"
                value={champions}
                onChange={setChampions}
                rows={4}
                placeholder={"0 infernus\n4 haze A"}
              />
            </Phase>
            <Phase status="lobby_code" current={now}>
              <Field className="w-48" label="Lobby code (when deadlock-api fails)" value={lobbyCode} onChange={setLobbyCode} placeholder={`DEV${match.id}`} />
            </Phase>
            <Phase status="in_progress" current={now}>
              <SimpleSelect
                className="w-48"
                label="Winner the captains report"
                value={winner}
                onChange={setWinner}
                options={[{ id: "", label: "default (A)" }, { id: "A", label: "Team A" }, { id: "B", label: "Team B" }]}
              />
            </Phase>
            <p className="mono text-xs text-muted">{match.players.map((p) => `${p.id}=${p.name}`).join("  ")}</p>
            {error ? <p role="alert" className="text-danger">{error}</p> : null}
          </Modal.Body>
          <Modal.Footer>
            <Button slot="close" variant="tertiary">Cancel</Button>
            <Button onPress={() => void save()}>Save script</Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
