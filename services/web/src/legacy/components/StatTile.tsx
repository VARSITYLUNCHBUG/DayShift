import { Card } from "@heroui/react";
import type { ReactNode } from "react";

interface Props {
  label: string;
  value: ReactNode;
  /** A line under the value: a chip, "59%", "Next off in 2 clean matches". */
  hint?: ReactNode;
  /** Smaller, for a row of facts about a match. */
  size?: "md" | "sm";
}

export function StatTile({ label, value, hint, size = "md" }: Props) {
  return (
    <Card className={size === "sm" ? "gap-1 p-4.5" : "gap-1.5 p-5"}>
      <span className="text-sm text-muted">{label}</span>
      <span className={`${size === "sm" ? "text-xl" : "text-3xl"} font-bold tabular-nums`}>{value}</span>
      {hint ? <span className="flex items-center gap-2 text-sm text-muted">{hint}</span> : null}
    </Card>
  );
}
