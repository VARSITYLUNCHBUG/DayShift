import { Chip } from "@heroui/react";

import type { MatchStatus } from "../../live/types";
import { STATUS_LABEL, STATUS_TONE } from "../match/status";

interface Props {
  status: MatchStatus;
  /** Shown after the label, e.g. the time in game: "In game · 24:10". */
  detail?: string | null;
  size?: "sm" | "md" | "lg";
}

export function StatusChip({ status, detail, size = "sm" }: Props) {
  const label = detail ? `${STATUS_LABEL[status]} · ${detail}` : STATUS_LABEL[status];
  return (
    <Chip color={STATUS_TONE[status]} variant="soft" size={size} className="tabular-nums">
      {label}
    </Chip>
  );
}
