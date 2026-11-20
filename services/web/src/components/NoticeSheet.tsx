import { useEffect, useId, useRef } from "react";
import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { Countdown } from "./Countdown";
import type { TeamKey } from "./team";
import { TEAM_CLASS } from "./team";

interface Props {
  isOpen: boolean;
  title: ReactNode;
  /** "Spot offered", "Early leave reported". */
  eyebrow?: ReactNode;
  /** The answer's server deadline: a 40px clock with "to answer". */
  deadline?: string | null;
  tone?: TeamKey | null;
  children?: ReactNode;
  /** The answers, main one first: "Take the spot", "Not now". */
  actions: ReactNode;
  /** Esc: usually the same as Not now. */
  onDismiss?: () => void;
  className?: string;
}

/** A notice that needs an answer soon (P04 rung 2): sub offers, swaps, early leaves. A side card
 * bottom-right on desktop, a bottom sheet below 1024. Not modal: focus moves to its heading when
 * it opens, but you can Tab away to finish what you were doing. One at a time. */
export function NoticeSheet({ isOpen, title, eyebrow, deadline, tone = null, children, actions, onDismiss, className }: Props) {
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (isOpen) heading.current?.focus();
  }, [isOpen]);

  if (!isOpen) return null;
  return (
    <section
      role="dialog"
      aria-modal="false"
      aria-labelledby={id}
      onKeyDownCapture={(event) => {
        if (event.key === "Escape" && onDismiss) {
          event.stopPropagation();
          onDismiss();
        }
      }}
      className={cn(
        "fixed inset-x-0 bottom-0 z-50 flex animate-enter flex-col gap-3.5 rounded-t-dialog border-2 bg-surface p-6 shadow-sheet",
        "lg:inset-x-auto lg:right-4 lg:bottom-4 lg:w-sheet lg:max-w-sheet lg:rounded-panel",
        tone ? TEAM_CLASS[tone].border : "border-line-strong",
        className,
      )}
    >
      {eyebrow ? <span className={cn("text-label font-bold", tone ? TEAM_CLASS[tone].text : "text-muted")}>{eyebrow}</span> : null}
      <h2 id={id} ref={heading} tabIndex={-1} className="text-sheet outline-none">
        {title}
      </h2>
      {deadline ? (
        <div className="flex items-baseline gap-2.5">
          <Countdown deadline={deadline} size="sheet" tone={tone} label="Time to answer" announce="to answer" />
          <span className="text-caption font-semibold text-muted">to answer</span>
        </div>
      ) : null}
      {children ? <div className="text-body text-muted">{children}</div> : null}
      <div className="flex flex-wrap gap-2.5 max-lg:*:flex-1">{actions}</div>
    </section>
  );
}
