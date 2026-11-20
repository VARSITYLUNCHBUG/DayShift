import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import type { PlayerSearch } from "../live/types";
import { getJson } from "./http";

/** The server answers nothing shorter (`reads.SEARCH_MIN`). */
export const SEARCH_MIN = 2;
const DEBOUNCE_MS = 250;

/** The text, once it has stopped changing for a moment. */
export function useDebounced(text: string, ms = DEBOUNCE_MS): string {
  const [settled, setSettled] = useState(text);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(text), ms);
    return () => clearTimeout(timer);
  }, [text, ms]);
  return settled;
}

/** GET /api/players/search/?q=: players of this server whose name contains the text. Asks
 * nothing until the text has two characters and has stopped changing. */
export function usePlayerSearch(text: string) {
  const query = useDebounced(text.trim());
  const enabled = query.length >= SEARCH_MIN;
  return useQuery({
    queryKey: ["players", "search", query],
    queryFn: () => getJson<PlayerSearch>(`/api/players/search/?${new URLSearchParams({ q: query }).toString()}`),
    enabled,
    staleTime: 10_000,
    // Keep the last list on screen while the next one loads.
    placeholderData: keepPreviousData,
    select: (data) => data.players,
  });
}
