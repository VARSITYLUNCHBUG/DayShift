import { ToggleButton, ToggleButtonGroup } from "@heroui/react";
import type { ReactNode } from "react";
import { Link, NavLink } from "react-router";

import { cn } from "../lib/cn";

const CHIP_TONE = {
  text: { text: "text-foreground", dot: "bg-foreground" },
  hk: { text: "text-team-hk", dot: "bg-team-hk" },
  am: { text: "text-team-am", dot: "bg-team-am" },
} as const;

interface StatusChipProps {
  to?: string;
  children: ReactNode;
  /** A dot for something happening now. */
  live?: boolean;
  tone?: keyof typeof CHIP_TONE;
}

/** "What you're in right now" (In the queue · 8/12, No. 413 · Your pick 0:27), in the top bar
 * on every page, linking back there. */
export function StatusChip({ to, children, live = false, tone = "text" }: StatusChipProps) {
  const classes = cn(
    "inline-flex h-11 items-center gap-2.5 rounded-full border-2 border-line-strong px-4 text-label font-bold whitespace-nowrap tabular-nums transition-state",
    CHIP_TONE[tone].text,
    to && "hover:border-foreground",
  );
  const inner = (
    <>
      {live ? <span aria-hidden="true" className={cn("size-2.25 rounded-full", CHIP_TONE[tone].dot)} /> : null}
      {children}
    </>
  );
  return to ? (
    <Link to={to} className={classes}>
      {inner}
    </Link>
  ) : (
    <span className={classes}>{inner}</span>
  );
}

export interface TabItem {
  label: string;
  to: string;
  /** Matches only this exact path (for an index tab). */
  end?: boolean;
}

/** Page-level tabs that are real links (postgame Summary · Timeline · Replay · Advanced). The
 * current one is bubblegum: identity, "where you are", not an action. Scrolls sideways on phones. */
export function PageTabs({ items, label }: { items: readonly TabItem[]; label: string }) {
  return (
    <nav aria-label={label} className="-mx-1 overflow-x-auto px-1 py-1">
      <ul className="flex gap-2">
        {items.map((item) => (
          <li key={item.to} className="shrink-0">
            <NavLink
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex h-11 items-center rounded-full border-2 px-5 text-body transition-state",
                  isActive
                    ? "border-brand bg-brand font-extrabold text-brand-ink"
                    : "border-line font-bold text-foreground hover:border-line-strong",
                )
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

interface SegmentedProps<K extends string> {
  options: readonly { id: K; label: ReactNode }[];
  value: K;
  onChange: (value: K) => void;
  /** The group's name: "View", "Team". */
  label: string;
}

/** A segmented control (one of a few views), on HeroUI's ToggleButtonGroup: the chosen one is
 * cream on ink. */
export function Segmented<K extends string>({ options, value, onChange, label }: SegmentedProps<K>) {
  return (
    <ToggleButtonGroup
      aria-label={label}
      selectionMode="single"
      disallowEmptySelection
      selectedKeys={[value]}
      onSelectionChange={(keys) => {
        const [first] = [...keys];
        if (first !== undefined) onChange(String(first) as K);
      }}
      className="segmented"
    >
      {options.map((option) => (
        <ToggleButton key={option.id} id={option.id} className="segmented__item">
          {option.label}
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  );
}

/** "Skip to content" (to #main) or, in the match room, "Skip to the match" (to #stage). The first
 * thing in the Tab order; visible only when focused. */
export function SkipLink({ to = "#main", children = "Skip to content" }: { to?: string; children?: ReactNode }) {
  return (
    <a
      href={to}
      className="sr-only rounded-full bg-foreground px-5 font-extrabold text-background focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:inline-flex focus:h-11 focus:items-center"
    >
      {children}
    </a>
  );
}
