import { vi } from "vitest";

import { PHONE_QUERY } from "../lib/useMediaQuery";

/** Makes the phone media query match (or not) for this test; restoreMocks puts it back. */
export function asPhone(phone = true): void {
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        matches: phone && query === PHONE_QUERY,
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  );
}
