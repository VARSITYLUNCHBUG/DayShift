import { ProgressBar, ProgressCircle } from "@heroui/react";
import type { ReactNode } from "react";

import { useCountdown } from "../../live/hooks";

const WAITING = "Waiting for server";

interface Props {
  deadline: string | null | undefined;
  className?: string;
}

/** "2:41", ticking with the server's clock; "Waiting for server" once it runs out. */
export function Countdown({ deadline, className }: Props) {
  const left = useCountdown(deadline);
  if (!left) return null;
  return (
    <span className={`tabular-nums ${className ?? ""}`} role="timer" aria-live="off">
      {left.waiting ? <span className="text-sm font-semibold text-muted">{WAITING}</span> : left.label}
    </span>
  );
}

type Tone = "accent" | "success" | "warning" | "danger";

/** The time left as a bar that empties. */
export function CountdownBar({
  deadline,
  tone = "accent",
  label = "Time left",
}: {
  deadline: string | null | undefined;
  tone?: Tone;
  label?: string;
}) {
  const left = useCountdown(deadline);
  if (!left) return null;
  const total = Math.max(1, Math.round(left.totalMs / 1000));
  return (
    <ProgressBar
      aria-label={label}
      value={left.seconds}
      maxValue={total}
      color={tone}
      size="md"
      valueLabel={left.waiting ? WAITING : left.label}
    >
      <ProgressBar.Track>
        <ProgressBar.Fill />
      </ProgressBar.Track>
    </ProgressBar>
  );
}

/** The time left as a ring, with the time and a caption in the middle (the ready check). */
export function CountdownRing({
  deadline,
  caption,
  tone = "success",
}: {
  deadline: string | null | undefined;
  caption?: ReactNode;
  tone?: Tone;
}) {
  const left = useCountdown(deadline);
  if (!left) return null;
  const total = Math.max(1, Math.round(left.totalMs / 1000));
  const text = left.waiting ? WAITING : left.label;
  return (
    <ProgressCircle
      aria-label={left.waiting ? WAITING : `${left.label} left`}
      value={left.seconds}
      maxValue={total}
      color={tone}
      className="relative size-48 sm:size-52"
    >
      <ProgressCircle.Track className="size-full">
        <ProgressCircle.TrackCircle />
        <ProgressCircle.FillCircle />
      </ProgressCircle.Track>
      <span className="absolute inset-0 flex flex-col items-center justify-center gap-0.5 text-center">
        <span
          className={`font-bold tabular-nums ${left.waiting ? "px-6 text-base" : "text-5xl"}`}
        >
          {text}
        </span>
        {caption ? <span className="text-sm text-muted tabular-nums">{caption}</span> : null}
      </span>
    </ProgressCircle>
  );
}
