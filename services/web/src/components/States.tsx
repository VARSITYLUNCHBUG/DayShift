import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { Mark } from "./Brand";
import { Icon } from "./Icon";

interface EmptyProps {
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  /** Art in place of the faded mark. */
  art?: ReactNode;
  className?: string;
}

/** Nothing here yet: what will appear and when. "No matches tonight yet. The first one starts
 * when 12 are in the queue." */
export function EmptyState({ title, children, action, art, className }: EmptyProps) {
  return (
    <div className={cn("flex flex-col items-center gap-3 rounded-panel border border-dashed border-line-strong px-6 py-12 text-center", className)}>
      {art ?? <Mark size={40} className="opacity-50" />}
      <b className="font-display text-card">{title}</b>
      {children ? <span className="max-w-105 text-body text-muted">{children}</span> : null}
      {action}
    </div>
  );
}

interface ErrorProps {
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  /** A quiet reference for support ("Match No. 413"), never an error code on its own. */
  code?: ReactNode;
  className?: string;
}

/** Something failed: what, what's kept and what to do. Never "Something went wrong" alone. */
export function ErrorState({ title, children, action, code, className }: ErrorProps) {
  return (
    <div
      role="alert"
      className={cn("flex flex-col items-center gap-3 rounded-panel border-2 border-danger bg-danger-soft px-6 py-12 text-center", className)}
    >
      <span className="text-danger">
        <Icon name="alert" size={32} />
      </span>
      <b className="font-display text-card">{title}</b>
      {children ? <span className="max-w-110 text-body text-muted">{children}</span> : null}
      {code ? <span className="text-caption font-bold text-faint">{code}</span> : null}
      {action}
    </div>
  );
}

const WIDTHS = ["w-3/5", "w-1/2", "w-2/5", "w-1/3", "w-1/4"] as const;
const SUB_WIDTHS = ["w-1/3", "w-2/5", "w-9/20", "w-1/2", "w-11/20"] as const;

/** Loading: still shapes, no shimmer (F06), named for screen readers. */
export function Skeleton({ lines = 4, label = "Loading", avatar = true }: { lines?: number; label?: string; avatar?: boolean }) {
  return (
    <div role="status" aria-label={label}>
      <ol className="flex flex-col gap-4" aria-hidden="true">
        {Array.from({ length: lines }, (_, i) => (
          <li key={i} className="flex items-center gap-3">
            {avatar ? <span className="size-10 shrink-0 rounded-full bg-raised" /> : null}
            <span className="flex flex-1 flex-col gap-1.5">
              <span className={cn("h-3 rounded-full bg-raised", WIDTHS[i % WIDTHS.length])} />
              <span className={cn("h-2.5 rounded-full border border-line bg-surface", SUB_WIDTHS[i % SUB_WIDTHS.length])} />
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
