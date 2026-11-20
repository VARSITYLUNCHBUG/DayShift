import type { ReactNode } from "react";

import { Countdown, CountdownBar } from "./Countdown";

type Tone = "accent" | "hk" | "am" | "default";

interface Props {
  /** The small line: "Pick 8 of 10 · Next: Vesper". */
  line?: ReactNode;
  /** "Your pick", "Vesper is picking". */
  title: ReactNode;
  deadline?: string | null;
  /** Show the time left as a bar under the clock too. */
  showBar?: boolean;
  tone?: Tone;
  /** The acting captain's buttons (Random, Lock in). */
  actions?: ReactNode;
}

const FRAME: Record<Tone, { box: string; line: string; bar: "accent" | "warning" }> = {
  accent: { box: "border-accent bg-accent-soft", line: "text-accent-soft-foreground", bar: "accent" },
  hk: {
    box: "border-team-hk/40 bg-team-hk-soft text-team-hk-soft-foreground",
    line: "text-team-hk",
    bar: "warning",
  },
  am: {
    box: "border-team-am/40 bg-team-am-soft text-team-am-soft-foreground",
    line: "text-team-am",
    bar: "accent",
  },
  default: { box: "border-border bg-surface", line: "text-muted", bar: "accent" },
};

/** Whose turn it is, with the clock. Highlighted when it's the viewer's turn. */
export function TurnBanner({ line, title, deadline, showBar = false, tone = "default", actions }: Props) {
  const frame = FRAME[tone];
  return (
    <section
      aria-label="Turn"
      className={`flex flex-wrap items-center gap-5 rounded-2xl border px-6 py-5 ${frame.box}`}
    >
      <div className="flex min-w-0 flex-1 basis-64 flex-col gap-1">
        {line ? <span className={`text-sm ${frame.line}`}>{line}</span> : null}
        <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
      </div>
      {deadline ? (
        <div className="flex w-full flex-col items-end gap-1.5 sm:w-48">
          <Countdown deadline={deadline} className="text-2xl font-bold sm:text-3xl" />
          {showBar ? (
            <div className="w-full">
              <CountdownBar deadline={deadline} tone={frame.bar} label="Turn time left" />
            </div>
          ) : null}
        </div>
      ) : null}
      {/* Phones: the buttons share one full-width row. */}
      {actions ? <div className="flex w-full gap-2.5 sm:w-auto sm:flex-wrap">{actions}</div> : null}
    </section>
  );
}
