import { Card } from "@heroui/react";
import type { ReactNode } from "react";

/** A titled card with an optional toolbar on the right of the header. */
export function Panel({
  title,
  actions,
  children,
  className = "",
}: {
  title: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={`gap-2 p-3 ${className}`}>
      <Card.Header className="flex flex-row flex-wrap items-center justify-between gap-2">
        <Card.Title className="text-sm font-semibold">{title}</Card.Title>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </Card.Header>
      <Card.Content className="min-h-0">{children}</Card.Content>
    </Card>
  );
}
