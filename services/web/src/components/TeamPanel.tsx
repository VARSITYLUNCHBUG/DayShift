import type { ReactNode } from "react";
import { useId } from "react";

import { cn } from "../lib/cn";
import { PlayerTile } from "./PlayerTile";
import type { PlayerTileProps } from "./PlayerTile";
import type { TeamKey } from "./team";
import { SIDE_NAME, TEAM_CLASS } from "./team";

interface Props {
  team: TeamKey;
  /** "Rook's Team": teams are named after their captain. */
  name: string;
  /** Under the name; the side's name by default. */
  line?: ReactNode;
  players: readonly (Omit<PlayerTileProps, "team" | "as"> & { id: string })[];
  className?: string;
}

/** One team's roster: its name in its colour, then the players. */
export function TeamPanel({ team, name, line, players, className }: Props) {
  const id = useId();
  return (
    <section
      aria-labelledby={id}
      className={cn("flex min-w-0 flex-1 basis-75 flex-col gap-2 rounded-panel border-2 p-4", TEAM_CLASS[team].softBorder, className)}
    >
      <div className="flex flex-wrap items-baseline gap-2.5">
        <h2 id={id} className={cn("text-section", TEAM_CLASS[team].text)}>
          {name}
        </h2>
        <span className={cn("text-caption font-bold", TEAM_CLASS[team].light)}>{line ?? SIDE_NAME[team]}</span>
      </div>
      <ol className="flex flex-col gap-0.5">
        {players.map(({ id: key, ...player }) => (
          <PlayerTile key={key} {...player} team={team} />
        ))}
      </ol>
    </section>
  );
}
