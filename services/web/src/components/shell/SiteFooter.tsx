import { useQuery } from "@tanstack/react-query";

import { getJson } from "../../api/http";
import { SESSION_KEY } from "../../api/session";
import type { Session } from "../../api/session";

/** South Africa's flag, drawn rather than the 🇿🇦 emoji: Windows has no flag emoji and would show
 * the letters "ZA". Its proportions are 2:3; the Y's bands are 1/5 of its height. */
function SouthAfricanFlag() {
  const arms = "M0 0L4.5 3L0 6M4.5 3H9";
  return (
    <svg viewBox="0 0 9 6" role="img" aria-label="South Africa" className="inline-block h-3 w-4.5 shrink-0 rounded-xs">
      <path d="M0 0h9v3H0z" className="fill-za-red" />
      <path d="M0 3h9v3H0z" className="fill-za-blue" />
      <path d={arms} fill="none" strokeWidth="2" className="stroke-za-white" />
      <clipPath id="za-hoist">
        <path d="M0 0L4.5 3L0 6z" />
      </clipPath>
      <path d="M0 0L4.5 3L0 6z" strokeWidth="2" clipPath="url(#za-hoist)" className="fill-za-black stroke-za-gold" />
      <path d={arms} fill="none" strokeWidth="1.2" className="stroke-za-green" />
    </svg>
  );
}

/** The foot of every page: who made it, and the hero art's credit (the art is the game's own).
 * The Ko-fi link shows once the server has one (KOFI_URL). */
export function SiteFooter({ underTabs = false }: { underTabs?: boolean }) {
  const { data } = useQuery({ queryKey: SESSION_KEY, queryFn: () => getJson<Session>("/api/session/"), staleTime: 60_000 });
  const kofi = data?.kofi_url ?? null;
  return (
    <footer
      data-under-tabs={underTabs || undefined}
      className="ds-site-footer mx-auto box-border flex w-full max-w-room flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 pb-6 text-micro text-faint md:px-8"
    >
      <ul className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <li>Made with Love &lt;3</li>
        <li aria-hidden="true">·</li>
        <li className="inline-flex items-center gap-1.5">
          Proudly <SouthAfricanFlag />
        </li>
        {kofi ? (
          <>
            {/* On a small screen Ko-fi takes a line of its own, so no dot is left at a line's end. */}
            <li aria-hidden="true" className="max-sm:hidden">
              ·
            </li>
            <li className="max-sm:basis-full">
              <a href={kofi} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-6 items-center font-bold underline underline-offset-2 hover:text-muted">
                Support us on Ko-fi
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            </li>
          </>
        ) : null}
      </ul>
      <span>Hero art © Valve</span>
    </footer>
  );
}
