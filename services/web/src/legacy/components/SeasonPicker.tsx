import { ListBox, Select } from "@heroui/react";
import type { Key } from "@heroui/react";
import { useSearchParams } from "react-router";

import { useSeasons } from "../../api/matches";

const SEASON_ID = /^[1-9][0-9]{0,18}$/;

/** The season the page shows, from `?season=<id>`: null for the open one. */
export function useSeasonParam(): string | null {
  const [params] = useSearchParams();
  const raw = params.get("season");
  return raw && SEASON_ID.test(raw) ? raw : null;
}

/** Picks the season for the leaderboard or a profile, kept in the URL so it can be shared.
 * Only there when the server has had more than one season. */
export function SeasonPicker({ value }: { value: string }) {
  const { data } = useSeasons();
  const [params, setParams] = useSearchParams();
  const seasons = data?.seasons ?? [];
  if (seasons.length < 2) return null;

  const choose = (key: Key | null) => {
    if (key === null) return;
    const id = String(key);
    const next = new URLSearchParams(params);
    if (seasons.find((season) => season.id === id)?.is_open) next.delete("season");
    else next.set("season", id);
    setParams(next);
  };

  return (
    <Select aria-label="Season" value={value} onChange={choose} variant="secondary" className="w-44">
      <Select.Trigger className="h-11">
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <ListBox>
          {seasons.map((season) => (
            <ListBox.Item key={season.id} id={season.id} textValue={season.name}>
              {season.is_open ? `${season.name} (now)` : season.name}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}
