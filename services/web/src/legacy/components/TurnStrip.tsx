import type { MatchSnap, Side } from "../../live/types";

export interface TurnStep {
  key: string;
  /** Short: "B1", "P2", or a captain's name. */
  label: string;
  /** For the tooltip and screen readers: "P2's Team ban, step 3". */
  title: string;
  side?: Side | null;
  state: "done" | "current" | "upcoming";
}

const UPCOMING: Record<Side | "none", string> = {
  hk: "bg-team-hk-soft text-team-hk-soft-foreground",
  am: "bg-team-am-soft text-team-am-soft-foreground",
  none: "bg-surface-tertiary text-foreground/80",
};
const CURRENT: Record<Side | "none", string> = {
  hk: "bg-team-hk text-team-hk-foreground ring-2 ring-team-hk ring-offset-2 ring-offset-background",
  am: "bg-team-am text-team-am-foreground ring-2 ring-team-am ring-offset-2 ring-offset-background",
  none: "bg-accent text-accent-foreground",
};

/** The draft order as a strip of steps: done, now, to come. */
export function TurnStrip({ steps, label = "Draft order" }: { steps: TurnStep[]; label?: string }) {
  return (
    <ol
      aria-label={label}
      className="grid gap-1"
      style={{ gridTemplateColumns: `repeat(${Math.max(1, steps.length)}, minmax(0, 1fr))` }}
    >
      {steps.map((step) => {
        const side = step.side ?? "none";
        const colour =
          step.state === "current"
            ? CURRENT[side]
            : step.state === "done"
              ? "bg-surface text-muted/60"
              : UPCOMING[side];
        return (
          <li
            key={step.key}
            title={step.title}
            aria-label={step.title}
            aria-current={step.state === "current" ? "step" : undefined}
            className={`flex h-8 min-w-0 items-center justify-center truncate rounded-lg px-0.5 text-xs font-bold ${colour}`}
          >
            {step.label}
          </li>
        );
      })}
    </ol>
  );
}

/** The hero draft's steps from a match snapshot (B1, P2, …), coloured by side. Team A is "1". */
export function championSteps(match: MatchSnap): TurnStep[] {
  const teamOf = (side: Side) => (match.sides.A === side ? "A" : match.sides.B === side ? "B" : null);
  const current = match.champion_step;
  const done = match.draft.filter((d) => d.action !== "player_pick").length;
  return match.champion_steps.map((step, index) => {
    const team = teamOf(step.side);
    const owner = team ? (match.team_names[team] ?? `Team ${team}`) : step.side.toUpperCase();
    return {
      key: String(index),
      label: `${step.action === "ban" ? "B" : "P"}${team === "B" ? "2" : "1"}`,
      title: `${owner} ${step.action}, step ${index + 1}`,
      side: step.side,
      state: index === current ? "current" : index < done ? "done" : "upcoming",
    };
  });
}
