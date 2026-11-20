import { useCallback, useSyncExternalStore } from "react";

/** Whether a media query matches, kept up to date. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** The phone shells (P08) take over below 768px: their own top bar, the tab bar, the sticky
 * footer action. Rendering one tree (not both, hidden by CSS) keeps one clock announcing. */
export const PHONE_QUERY = "(max-width: 767.98px)";

export function useIsPhone(): boolean {
  return useMediaQuery(PHONE_QUERY);
}
