import { ListBox, Select } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";

import { queries } from "../../api/queries";

/** The season a page shows, from `?season=<id>`: null for the open one. */
export function useSeasonParam(): string | null {
  const [params] = useSearchParams();
  const raw = params.get("season");
  return raw && /^[1-9][0-9]{0,18}$/.test(raw) ? raw : null;
}

/** Picks the season (Ladder, Me). Only there once the server has had more than one. */
export function SeasonSwitch({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
  const seasons = useQuery(queries.seasons());
  const list = seasons.data?.seasons ?? [];
  if (list.length < 2) return null;
  const open = list.find((s) => s.is_open)?.id ?? null;
  return (
    <Select
      aria-label="Season"
      variant="secondary"
      className="w-56"
      value={value ?? open ?? list[0]?.id ?? null}
      onChange={(key) => {
        if (key !== null) onChange(String(key) === open ? null : String(key));
      }}
    >
      <Select.Trigger className="min-h-11">
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <ListBox>
          {list.map((season) => (
            <ListBox.Item key={season.id} id={season.id} textValue={season.name}>
              {season.name}
              {season.is_open ? " · now" : ""}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}
