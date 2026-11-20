import { HeroCard } from "./HeroCard";
import type { HeroCardProps } from "./HeroCard";
import { PickGrid } from "./PickGrid";

export interface HeroChoice extends Omit<HeroCardProps, "className" | "state"> {
  id: string;
  /** Taken (picked by a side) or banned: not pickable. */
  state?: "free" | "banned" | "hk" | "am" | "locked";
}

interface Props {
  heroes: readonly HeroChoice[];
  selectedId?: string | null;
  /** Leave out while waiting or watching: the grid stays browsable. */
  onSelect?: (id: string) => void;
  "aria-label"?: string;
}

function label(hero: HeroChoice): string {
  if (hero.state === "banned") return `${hero.name}, banned`;
  if (typeof hero.tag === "string" && hero.tag) return `${hero.name}, ${hero.tag}`;
  return hero.name;
}

/** Every hero, for banning or picking: 6 across at 1440, 5, 4, 3 on a phone. */
export function HeroGrid({ heroes, selectedId = null, onSelect, ...aria }: Props) {
  return (
    <PickGrid
      aria-label={aria["aria-label"] ?? "Heroes"}
      items={heroes}
      getKey={(hero) => hero.id}
      getLabel={label}
      selectedKey={selectedId}
      onSelect={onSelect}
      disabledKeys={heroes.filter((hero) => hero.state && hero.state !== "free").map((hero) => hero.id)}
      renderItem={(hero, { isSelected }) => {
        const { id: _id, state = "free", ...card } = hero;
        return <HeroCard {...card} state={isSelected && state === "free" ? "selected" : state} />;
      }}
    />
  );
}
