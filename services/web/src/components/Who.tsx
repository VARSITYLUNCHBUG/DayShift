import { cn } from "../lib/cn";
import { Tag } from "./Sticker";
import type { TeamKey } from "./team";

interface Props {
  name: string;
  /** The clan tag, as the player set it. */
  tag?: string | null;
  /** The team inside a match; leave out outside one (neutral tag). */
  team?: TeamKey | null;
  /** Adds the quiet "you" marker. */
  isYou?: boolean;
  className?: string;
}

/** Tag and name, the way every player is shown. */
export function Who({ name, tag, team, isYou = false, className }: Props) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-2 font-bold", className)}>
      {tag ? <Tag team={team}>{tag}</Tag> : null}
      <span className="truncate">{name}</span>
      {isYou ? <span className="text-micro font-semibold text-muted">you</span> : null}
    </span>
  );
}
