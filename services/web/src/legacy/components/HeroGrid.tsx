import { teamName } from "../lib/format";
import type { ChampionChoice, MatchSnap, Side } from "../../live/types";
import { HeroCard } from "./HeroCard";

export interface HeroTag {
  label: string;
  tone?: Side | "danger" | "success";
}

interface Props {
  champions: ChampionChoice[];
  selectedId?: string | null;
  /** Leave out to show the grid without picking (waiting or watching). */
  onSelect?: (id: string) => void;
  isDisabled?: boolean;
  /** Why a taken hero is taken: "Banned", "P2's Team". */
  tags?: Record<string, HeroTag>;
}

/** Every hero, for picking or banning. Taken ones can't be pressed. */
export function HeroGrid({ champions, selectedId = null, onSelect, isDisabled = false, tags = {} }: Props) {
  return (
    <ul className="grid grid-cols-3 gap-2.5 sm:grid-cols-4 lg:grid-cols-6" aria-label="Heroes">
      {champions.map((champion) => {
        const tag = tags[champion.id];
        const selected = champion.id === selectedId;
        const label = champion.taken
          ? `${champion.name}, ${tag?.label.toLowerCase() ?? "taken"}`
          : onSelect
            ? `Pick ${champion.name}`
            : champion.name;
        return (
          <li key={champion.id}>
            <HeroCard
              champion={champion}
              tag={tag?.label ?? (selected ? "Selected" : null)}
              tone={tag?.tone ?? (selected ? "success" : undefined)}
              isSelected={selected}
              isTaken={champion.taken}
              isDisabled={isDisabled || champion.taken}
              onPress={onSelect ? () => onSelect(champion.id) : undefined}
              aria-label={label}
            />
          </li>
        );
      })}
    </ul>
  );
}

/** Why each taken hero is taken, from the draft so far. */
export function heroTags(match: MatchSnap): Record<string, HeroTag> {
  const tags: Record<string, HeroTag> = {};
  for (const entry of match.draft) {
    if (!entry.champion || !entry.team) continue;
    const side = match.sides[entry.team];
    tags[entry.champion.id] =
      entry.action === "ban"
        ? { label: "Banned", tone: "danger" }
        : { label: teamName(match.team_names, entry.team), tone: side ?? undefined };
  }
  return tags;
}
