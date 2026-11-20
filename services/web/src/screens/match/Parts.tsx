// Small pieces the room's screens share.
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

/** The stage's heading: an eyebrow, the display title, a lead, and the one action on desktop
 * (phones carry it in the sticky footer). */
export function StageHead({
  eyebrow,
  title,
  lead,
  action,
  tone,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  lead?: ReactNode;
  action?: ReactNode;
  /** The eyebrow's colour class. */
  tone?: string;
}) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-4">
      <div className="flex min-w-0 flex-1 basis-80 flex-col gap-2">
        {eyebrow ? <span className={cn("text-label font-bold", tone)}>{eyebrow}</span> : null}
        <h1 className="text-board max-md:text-coin">{title}</h1>
        {lead ? <p className="max-w-lead text-lead text-muted">{lead}</p> : null}
      </div>
      {action ? <div className="flex flex-wrap gap-2.5 max-md:hidden">{action}</div> : null}
    </header>
  );
}

/** A quiet panel of "what happens next" copy. */
export function Note({ title, children, className }: { title: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("flex flex-col gap-1.5 rounded-panel border border-line bg-surface px-5 py-4.5", className)}>
      <h2 className="text-body font-extrabold font-sans tracking-normal">{title}</h2>
      <div className="text-caption text-muted">{children}</div>
    </section>
  );
}
