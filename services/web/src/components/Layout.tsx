import { useId } from "react";
import type { ReactNode } from "react";

import { cn } from "../lib/cn";

/** A panel: groups content on the surface, 20px radius, 1px line. */
export function Panel({
  children,
  className,
  as: Element = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "aside";
}) {
  return <Element className={cn("rounded-panel border border-line bg-surface p-5", className)}>{children}</Element>;
}

interface SectionProps {
  title: ReactNode;
  children: ReactNode;
  /** Something on the title's right: a link, a filter. */
  aside?: ReactNode;
  /** h2 by default. */
  level?: 2 | 3;
  className?: string;
}

/** A page section: a display-type title over a line, then the content. */
export function Section({ title, children, aside, level = 2, className }: SectionProps) {
  const id = useId();
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <section aria-labelledby={id} className={cn("flex flex-col gap-3.5", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line pb-2.5">
        <Heading id={id} className={level === 2 ? "text-section" : "text-card"}>
          {title}
        </Heading>
        {aside}
      </div>
      {children}
    </section>
  );
}

interface PageHeaderProps {
  title: ReactNode;
  lead?: ReactNode;
  eyebrow?: ReactNode;
  className?: string;
}

/** A page's title and its lead line. */
export function PageHeader({ title, lead, eyebrow, className }: PageHeaderProps) {
  return (
    <header className={cn("flex flex-col gap-3", className)}>
      {eyebrow ? <span className="text-label font-bold text-muted">{eyebrow}</span> : null}
      <h1 className="text-title max-md:text-coin">{title}</h1>
      {lead ? <p className="max-w-lead text-lead text-muted">{lead}</p> : null}
    </header>
  );
}
