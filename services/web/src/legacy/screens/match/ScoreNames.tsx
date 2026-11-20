import { Button, Card, Chip, Label, ListBox, Select, Spinner } from "@heroui/react";
import type { Key } from "@heroui/react";
import { useState } from "react";

import { HeroArt } from "../../components/HeroCard";
import { notify } from "../../components/toast";
import { initials, plural, teamName } from "../../lib/format";
import { useAction } from "../../../live/hooks";
import type { MatchSnap, Scoreboard, ScoreboardRow, Side } from "../../../live/types";

const ROW_TONE: Record<Side, string> = {
  hk: "bg-team-hk-soft text-team-hk-soft-foreground",
  am: "bg-team-am-soft text-team-am-soft-foreground",
};

/** 3.5 Match scoreboard names: the scoreboard's in-game names the server couldn't place, each
 * matched by a captain to a player on that row's team (`ocr.map_row`). Remembered for next time. */
export function ScoreNames({ match, scoreboard }: { match: MatchSnap; scoreboard: Scoreboard }) {
  const action = useAction();
  // Row number → player ID. A row the server has matched since drops out with its snapshot.
  const [chosen, setChosen] = useState<Record<number, string>>({});
  const [saving, setSaving] = useState(false);
  const rows = new Set(scoreboard.rows.map((r) => r.row));
  const picks = Object.entries(chosen)
    .map(([row, player]) => ({ row: Number(row), player }))
    .filter((pick) => rows.has(pick.row));

  const choose = (row: number, key: Key | null) => {
    setChosen((current) => {
      const next = { ...current };
      if (key === null) delete next[row];
      else next[row] = String(key);
      return next;
    });
  };

  const save = async () => {
    setSaving(true);
    try {
      // One at a time: each match is checked against the ones before it.
      for (const pick of picks) {
        await action.run("ocr.map_row", { read_id: scoreboard.read_id, row: pick.row, player_id: pick.player });
      }
      setChosen({});
      notify.success("Names saved");
    } catch (reason) {
      notify.error(reason);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card aria-labelledby={`names-${scoreboard.read_id}`} className="w-full max-w-140 gap-4.5 border border-border p-7">
      <div className="flex items-center justify-between gap-3">
        <h2 id={`names-${scoreboard.read_id}`} className="text-2xl font-bold">
          Match scoreboard names
        </h2>
        <Chip color="warning" variant="soft" size="sm" className="font-bold">
          {scoreboard.rows.length} left
        </Chip>
      </div>
      <p className="text-sm text-muted">Who played each of these? It&apos;s remembered for next time.</p>
      <ul aria-label="Unmatched names" className="flex flex-col gap-2.5">
        {scoreboard.rows.map((row) => (
          <NameRow
            key={row.row}
            match={match}
            row={row}
            options={scoreboard.players.filter(
              (p) =>
                p.team === row.team &&
                // Each player matches one name: hide those chosen for another row.
                !picks.some((pick) => pick.row !== row.row && pick.player === p.id),
            )}
            value={chosen[row.row] ?? null}
            onChange={(key) => choose(row.row, key)}
          />
        ))}
      </ul>
      <Button
        size="lg"
        fullWidth
        isDisabled={picks.length === 0}
        isPending={saving}
        onPress={() => void save()}
        className="h-13 rounded-2xl text-base font-bold"
      >
        {({ isPending }) => (
          <>
            {isPending ? <Spinner color="current" size="sm" /> : null}
            {picks.length > 1 ? `Save ${plural(picks.length, "name")}` : "Save names"}
          </>
        )}
      </Button>
    </Card>
  );
}

interface RowProps {
  match: MatchSnap;
  row: ScoreboardRow;
  options: Scoreboard["players"];
  value: string | null;
  onChange: (key: Key | null) => void;
}

function NameRow({ match, row, options, value, onChange }: RowProps) {
  const side = match.sides[row.team];
  const hero = row.hero?.name ?? row.hero_name;
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-background p-3.5">
      {row.hero ? (
        <HeroArt champion={row.hero} className="h-13 w-10 shrink-0 overflow-hidden rounded-lg" />
      ) : (
        <span
          aria-hidden="true"
          className={`flex h-13 w-10 shrink-0 items-center justify-center rounded-lg text-sm font-bold ${side ? ROW_TONE[side] : "bg-surface-tertiary"}`}
        >
          {initials(hero || row.name)}
        </span>
      )}
      <span className="flex min-w-40 flex-1 flex-col gap-0.5">
        <span className="text-base font-semibold break-all">{row.name || "?"}</span>
        <span className="text-sm text-muted">{[hero, teamName(match.team_names, row.team)].filter(Boolean).join(" · ")}</span>
      </span>
      <Select
        placeholder="Choose a player"
        value={value}
        onChange={onChange}
        variant="secondary"
        className="min-w-44"
      >
        <Label className="sr-only">Player for {row.name || "this name"}</Label>
        <Select.Trigger className="h-11">
          <Select.Value />
          <Select.Indicator />
        </Select.Trigger>
        <Select.Popover>
          <ListBox>
            {options.map((player) => (
              <ListBox.Item key={player.id} id={player.id} textValue={player.name}>
                {player.name}
                <ListBox.ItemIndicator />
              </ListBox.Item>
            ))}
          </ListBox>
        </Select.Popover>
      </Select>
    </li>
  );
}
