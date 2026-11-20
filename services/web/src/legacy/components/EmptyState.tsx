import type { ReactNode } from "react";

import { EmptyState as DayShiftEmptyState } from "../../components/States";

interface Props {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

/** The old screens' empty state, drawn as DayShift's. */
export function EmptyState({ title, description, icon, action, className }: Props) {
  return (
    <DayShiftEmptyState title={title} action={action} art={icon ? <span className="text-muted">{icon}</span> : undefined} className={className}>
      {description}
    </DayShiftEmptyState>
  );
}
