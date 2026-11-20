import type { ReactNode } from "react";

import { cn } from "../lib/cn";

export type InlineAlertKind = "danger" | "info" | "success" | "warn";

const KIND: Record<InlineAlertKind, string> = {
  danger: "border-danger bg-danger-soft",
  info: "border-line-strong bg-raised",
  success: "border-ok bg-raised",
  warn: "border-foreground bg-raised-2",
};

interface Props {
  kind?: InlineAlertKind;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  id?: string;
  className?: string;
}

/** About what you just tried (P04 rung 5): a refusal or a field error, right where you acted.
 * Plain words and the fix, never a code. Read out at once (role=alert); stays until fixed. */
export function InlineAlert({ kind = "danger", title, children, action, id, className }: Props) {
  return (
    <div id={id} role="alert" className={cn("flex flex-col gap-2 rounded-card border-2 px-4.5 py-4", KIND[kind], className)}>
      <b className="text-body font-extrabold">{title}</b>
      {children ? <span className="text-label text-muted">{children}</span> : null}
      {action ? <div>{action}</div> : null}
    </div>
  );
}
