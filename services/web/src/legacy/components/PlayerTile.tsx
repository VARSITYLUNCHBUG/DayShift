import { Check } from "@gravity-ui/icons";
import type { ReactNode } from "react";

import { PlayerAvatar } from "./PlayerAvatar";

export type PlayerTileState = "ready" | "you" | "waiting" | "plain";

interface Props {
  name: string;
  avatarUrl?: string | null;
  /** ready: ticked, green. you: the viewer, still to act. waiting: still to act. */
  state?: PlayerTileState;
  /** Right-hand detail: a rating, "C" for captain, "Joined". */
  detail?: ReactNode;
  showAvatar?: boolean;
  /** Tighter rows, for a team's list. */
  dense?: boolean;
}

const FRAME: Record<PlayerTileState, string> = {
  ready: "border-success/30 bg-success-soft",
  you: "border-accent bg-accent-soft font-semibold",
  waiting: "border-border bg-surface text-muted",
  plain: "border-transparent",
};

/** One player in a list or grid: avatar (or a ready tick), name, and a detail. */
export function PlayerTile({
  name,
  avatarUrl = null,
  state = "plain",
  detail,
  showAvatar = false,
  dense = false,
}: Props) {
  return (
    <div
      className={`flex items-center gap-2.5 rounded-xl border text-sm ${dense ? "min-h-9 px-2.5 py-2" : "min-h-11 p-3"} ${FRAME[state]}`}
    >
      {state === "ready" ? (
        <Check width={16} height={16} className="shrink-0 text-success" role="img" aria-label="Ready" />
      ) : state === "you" || state === "waiting" ? (
        <span
          role="img"
          aria-label="Not ready"
          className={`size-4 shrink-0 rounded-full border-2 ${state === "you" ? "border-accent-soft-foreground" : "border-default"}`}
        />
      ) : null}
      {showAvatar ? <PlayerAvatar name={name} url={avatarUrl} /> : null}
      <span className={`min-w-0 flex-1 truncate ${state === "waiting" ? "text-foreground/80" : ""}`}>{name}</span>
      {detail !== undefined ? <span className="shrink-0 text-xs font-semibold text-muted">{detail}</span> : null}
    </div>
  );
}
