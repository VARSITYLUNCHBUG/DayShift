import { Button, Checkbox, Chip, Input, Modal, SearchField, Switch } from "@heroui/react";
import { useCallback, useMemo, useState } from "react";

import { control, type CreatePlayersInput, type Player } from "../api";
import { Field } from "../components/Field";
import { Panel } from "../components/Panel";
import { Toggle } from "../components/Toggle";
import { describeError, useAction } from "../hooks/useAction";
import { usePoll } from "../hooks/usePoll";
import { parseList } from "../lib/match";

const loadPlayers = (signal: AbortSignal) => control.players(signal);

function AddPlayers({ onAdd }: { onAdd: (input: CreatePlayersInput) => Promise<unknown> }) {
  const [count, setCount] = useState("4");
  const [min, setMin] = useState("1500");
  const [max, setMax] = useState("");
  const [prefix, setPrefix] = useState("");
  const [dmOpen, setDmOpen] = useState(true);
  const [joinQueue, setJoinQueue] = useState(false);

  const submit = () => {
    const n = Number.parseInt(count, 10);
    if (!Number.isFinite(n) || n < 1) return;
    const input: CreatePlayersInput = { count: n, dm_open: dmOpen, join_queue: joinQueue };
    const lo = Number.parseFloat(min);
    const hi = Number.parseFloat(max);
    if (Number.isFinite(lo) && Number.isFinite(hi)) input.rating = { min: Math.min(lo, hi), max: Math.max(lo, hi) };
    else if (Number.isFinite(lo)) input.rating = lo;
    if (prefix.trim()) input.name_prefix = prefix.trim();
    void onAdd(input);
  };

  return (
    <Panel title="Add fake players">
      <div className="flex flex-wrap items-end gap-3">
        <Field className="w-20" label="Count" type="number" value={count} onChange={setCount} onEnter={submit} />
        <Field className="w-28" label="Rating (or min)" type="number" value={min} onChange={setMin} onEnter={submit} />
        <Field className="w-28" label="Max (range)" type="number" value={max} onChange={setMax} placeholder="—" onEnter={submit} />
        <Field className="w-40" label="Name prefix" value={prefix} onChange={setPrefix} placeholder="auto" onEnter={submit} />
        <div className="flex flex-col gap-2 pb-1">
          <Toggle label="DMs open" isSelected={dmOpen} onChange={setDmOpen} />
          <Toggle label="Join queue" isSelected={joinQueue} onChange={setJoinQueue} />
        </div>
        <Button onPress={submit}>Add players</Button>
      </div>
    </Panel>
  );
}

function RatingCell({ player, onSave }: { player: Player; onSave: (rating: number) => void }) {
  const initial = player.rating === null ? "" : String(Math.round(player.rating));
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft === null) return;
    const value = Number.parseFloat(draft);
    setDraft(null);
    if (Number.isFinite(value) && draft !== initial) onSave(value);
  };
  return (
    <Input
      variant="secondary"
      aria-label={`Rating of ${player.name}`}
      className="mono w-24"
      type="number"
      value={draft ?? initial}
      onChange={(e) => { setDraft(e.target.value); }}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
        if (e.key === "Escape") setDraft(null);
      }}
    />
  );
}

function PicksEditor({
  player,
  onClose,
  onSave,
}: {
  player: Player;
  onClose: () => void;
  /** Resolves to undefined when the save failed, so the editor stays open. */
  onSave: (prefer: string[], ban: string[]) => Promise<unknown>;
}) {
  const [prefer, setPrefer] = useState(player.picks.prefer.join(", "));
  const [ban, setBan] = useState(player.picks.ban.join(", "));
  return (
    <Modal.Backdrop isOpen onOpenChange={(open) => { if (!open) onClose(); }}>
      <Modal.Container size="md">
        <Modal.Dialog>
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Heading>Champion plan: {player.name}</Modal.Heading>
          </Modal.Header>
          <Modal.Body className="flex flex-col gap-3">
            <p className="text-muted">
              Champion slugs, comma or space separated, in order of preference. Autopilot uses these
              when this player is captain for a pick or ban.
            </p>
            <Field label="Preferred" value={prefer} onChange={setPrefer} placeholder="haze, infernus" autoFocus />
            <Field label="Banned" value={ban} onChange={setBan} placeholder="seven" />
          </Modal.Body>
          <Modal.Footer>
            <Button slot="close" variant="tertiary">Cancel</Button>
            <Button
              onPress={() => {
                void onSave(parseList(prefer), parseList(ban)).then((saved) => {
                  if (saved !== undefined) onClose();
                });
              }}
            >
              Save plan
            </Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}

/** Screen 1: create fake players and tune each one. */
export function PlayersScreen({ onChanged }: { onChanged: () => void }) {
  const players = usePoll(loadPlayers, 2000);
  const refreshPlayers = players.refresh;
  const after = useCallback(() => {
    refreshPlayers();
    onChanged();
  }, [refreshPlayers, onChanged]);
  const { run, pending } = useAction(after);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<Player | null>(null);

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    const all = players.data ?? [];
    return q ? all.filter((p) => p.name.toLowerCase().includes(q) || String(p.id) === q) : all;
  }, [players.data, query]);

  const toggle = (id: number, on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  };
  const allSelected = list.length > 0 && list.every((p) => selected.has(p.id));
  const selectedIds = list.filter((p) => selected.has(p.id)).map((p) => p.id);

  return (
    <div className="flex flex-col gap-4">
      <AddPlayers onAdd={(input) => run("Add players", () => control.createPlayers(input), `Added ${input.count}`)} />
      <Panel
        title={`Players (${players.data?.length ?? 0})`}
        actions={
          <>
            <SearchField variant="secondary" aria-label="Filter players" value={query} onChange={setQuery} className="w-56">
              <SearchField.Group>
                <SearchField.SearchIcon />
                <SearchField.Input placeholder="Filter by name or id" />
                <SearchField.ClearButton />
              </SearchField.Group>
            </SearchField>
            <Button
              size="sm"
              variant="secondary"
              isDisabled={selectedIds.length === 0}
              onPress={() => void run("Join queue", () => control.joinQueue({ player_ids: selectedIds }))}
            >
              Queue selected
            </Button>
            <Button
              size="sm"
              variant="secondary"
              isDisabled={selectedIds.length === 0}
              onPress={() => void run("Leave queue", () => control.leaveQueue(selectedIds))}
            >
              Unqueue selected
            </Button>
          </>
        }
      >
        {players.error ? <p className="mb-2 text-danger">Players: {describeError(players.error)}</p> : null}
        <div className="overflow-auto">
          <table className="w-full border-collapse text-left">
            <thead className="text-muted">
              <tr className="border-b border-border">
                <th className="w-8 py-1">
                  <Checkbox
                    variant="secondary"
                    aria-label="Select all"
                    isSelected={allSelected}
                    onChange={(on) => { setSelected(on ? new Set(list.map((p) => p.id)) : new Set()); }}
                  >
                    <Checkbox.Content>
                      <Checkbox.Control>
                        <Checkbox.Indicator />
                      </Checkbox.Control>
                    </Checkbox.Content>
                  </Checkbox>
                </th>
                <th className="py-1">ID</th>
                <th className="py-1">Name</th>
                <th className="py-1">Discord id</th>
                <th className="py-1">Rating</th>
                <th className="py-1">DMs</th>
                <th className="py-1">Where</th>
                <th className="py-1">Champion plan</th>
                <th className="py-1" />
              </tr>
            </thead>
            <tbody>
              {list.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-6 text-center text-muted">
                    {players.data ? "No players yet. Add some above." : "Loading…"}
                  </td>
                </tr>
              ) : null}
              {list.map((p) => (
                <tr key={p.id} className="border-b border-separator hover:bg-surface-hover">
                  <td className="py-1">
                    <Checkbox
                      variant="secondary"
                      aria-label={`Select ${p.name}`}
                      isSelected={selected.has(p.id)}
                      onChange={(on) => { toggle(p.id, on); }}
                    >
                      <Checkbox.Content>
                        <Checkbox.Control>
                          <Checkbox.Indicator />
                        </Checkbox.Control>
                      </Checkbox.Content>
                    </Checkbox>
                  </td>
                  <td className="mono py-1">{p.id}</td>
                  <td className="py-1">{p.name}</td>
                  <td className="mono py-1 text-muted">{p.discordId ?? "—"}</td>
                  <td className="py-1">
                    <RatingCell
                      player={p}
                      onSave={(rating) => void run("Set rating", () => control.updatePlayer(p.id, { rating }))}
                    />
                  </td>
                  <td className="py-1">
                    <Switch
                      size="sm"
                      aria-label={`DMs open for ${p.name}`}
                      isSelected={p.dmOpen ?? true}
                      onChange={(on) => void run("DMs", () => control.updatePlayer(p.id, { dm_open: on }))}
                    >
                      <Switch.Content>
                        <Switch.Control>
                          <Switch.Thumb />
                        </Switch.Control>
                      </Switch.Content>
                    </Switch>
                  </td>
                  <td className="py-1">
                    {p.matchId !== null ? (
                      <Chip size="sm" color="accent" variant="soft">match #{p.matchId}</Chip>
                    ) : p.inQueue ? (
                      <Chip size="sm" color="success" variant="soft">queued</Chip>
                    ) : (
                      <span className="text-muted">idle</span>
                    )}
                  </td>
                  <td className="py-1">
                    <Button size="sm" variant="ghost" onPress={() => { setEditing(p); }}>
                      {p.picks.prefer.length || p.picks.ban.length ? (
                        <span className="mono">
                          +{p.picks.prefer.slice(0, 3).join(",")}
                          {p.picks.ban.length ? ` −${p.picks.ban.join(",")}` : ""}
                        </span>
                      ) : (
                        "Edit…"
                      )}
                    </Button>
                  </td>
                  <td className="py-1 text-right">
                    <Button
                      size="sm"
                      variant="danger-soft"
                      isDisabled={pending !== null}
                      onPress={() => void run("Delete player", () => control.deletePlayer(p.id), `Deleted ${p.name}`)}
                    >
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      {editing ? (
        <PicksEditor
          key={editing.id}
          player={editing}
          onClose={() => { setEditing(null); }}
          onSave={(prefer, ban) => run("Save plan", () => control.setPicks(editing.id, { prefer, ban }))}
        />
      ) : null}
    </div>
  );
}
