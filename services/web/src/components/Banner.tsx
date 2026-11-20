import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { Icon } from "./Icon";

export type BannerKind = "info" | "warn" | "danger";

const KIND = {
  info: { box: "bg-raised border-line", icon: "clock", tone: "text-foreground" },
  warn: { box: "bg-raised-2 border-line-strong", icon: "wifi", tone: "text-foreground" },
  danger: { box: "bg-danger-soft border-line", icon: "alert", tone: "text-danger" },
} as const;

interface Props {
  kind?: BannerKind;
  title?: ReactNode;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}

/** The state of the app (P04 rung 3): reconnecting, offline, paused, restarting. Full width
 * under the top bar or room header for as long as the state lasts; not dismissable. */
export function Banner({ kind = "info", title, children, action, className }: Props) {
  const style = KIND[kind];
  return (
    <div
      role="status"
      className={cn("flex flex-wrap items-center gap-x-3.5 gap-y-2.5 border-b-2 px-4 py-3 md:px-8", style.box, className)}
    >
      <span className={style.tone}>
        <Icon name={style.icon} size={18} />
      </span>
      <span className="text-body font-semibold text-foreground">
        {title ? <b className="font-extrabold">{title} </b> : null}
        {children}
      </span>
      {action ? <div className="ml-auto">{action}</div> : null}
    </div>
  );
}
