import { PickGrid } from "./PickGrid";
import { PlayerTile } from "./PlayerTile";
import type { PlayerTileProps } from "./PlayerTile";
import { cn } from "../lib/cn";

export interface PlayerChoice extends Omit<PlayerTileProps, "as" | "action" | "className"> {
  id: string;
  isTaken?: boolean;
}

interface Props {
  players: readonly PlayerChoice[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  "aria-label"?: string;
}

/** The players still to pick in the player draft: one Tab stop, arrows move, Enter picks. */
export function PlayerGrid({ players, selectedId = null, onSelect, ...aria }: Props) {
  return (
    <PickGrid
      aria-label={aria["aria-label"] ?? "Players left"}
      items={players}
      getKey={(player) => player.id}
      getLabel={(player) => (typeof player.line === "string" ? `${player.name}, ${player.line}` : player.name)}
      selectedKey={selectedId}
      onSelect={onSelect}
      disabledKeys={players.filter((player) => player.isTaken).map((player) => player.id)}
      columns="grid-cols-1 sm:grid-cols-2 xl:grid-cols-3"
      className="gap-2"
      renderItem={({ id: _id, isTaken, ...player }, { isSelected }) => (
        <PlayerTile
          {...player}
          as="div"
          className={cn(
            "border-2 bg-surface transition-state",
            isSelected ? "border-foreground" : "border-line",
            isTaken && "opacity-50",
          )}
        />
      )}
    />
  );
}
