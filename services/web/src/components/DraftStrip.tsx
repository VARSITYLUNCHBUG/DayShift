import { cn } from "../lib/cn";
import type { TeamKey } from "./team";
import { SIDE_NAME } from "./team";

export interface DraftStep {
  kind: "ban" | "pick";
  team: TeamKey;
  /** The hero, once the step is done. */
  hero?: string | null;
  /** The clock ran out and the bot picked at random. */
  isRandom?: boolean;
}

interface Props {
  steps: readonly DraftStep[];
  /** The step on the clock; steps before it are done. Past the end when the draft is complete. */
  current: number;
}

const ON_CLOCK: Record<TeamKey, string> = {
  hk: "bg-team-hk text-team-hk-ink border-team-hk",
  am: "bg-team-am text-team-am-ink border-team-am",
};

const AHEAD: Record<TeamKey, string> = {
  hk: "bg-team-hk-soft text-team-hk-light border-team-hk-soft",
  am: "bg-team-am-soft text-team-am-light border-team-am-soft",
};

/** The draft order: one cell per ban or pick. Done ones carry the hero (bans struck through), the
 * current one is solid in its side's colour. A list to read, not a tab stop. */
export function DraftStrip({ steps, current }: Props) {
  return (
    <div className="overflow-x-auto">
      <ol
        aria-label="Draft order"
        className="grid gap-0.75"
        style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(2.75rem, 1fr))` }}
      >
        {steps.map((step, index) => {
          const done = index < current;
          const now = index === current;
          const kind = step.kind === "ban" ? "Ban" : "Pick";
          const label = `${SIDE_NAME[step.team].replace("The ", "")} ${step.kind}, step ${index + 1}${
            step.hero ? `: ${step.hero}${step.isRandom ? " (random)" : ""}` : ""
          }`;
          return (
            <li
              key={index}
              aria-label={label}
              aria-current={now ? "step" : undefined}
              className={cn(
                "flex h-10 items-center justify-center truncate rounded-small border px-1 text-micro font-extrabold",
                now ? ON_CLOCK[step.team] : done ? "border-line bg-background text-faint" : AHEAD[step.team],
                done && step.kind === "ban" && "line-through",
              )}
            >
              <span aria-hidden="true" className="truncate">
                {done && step.hero ? step.hero : kind}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
