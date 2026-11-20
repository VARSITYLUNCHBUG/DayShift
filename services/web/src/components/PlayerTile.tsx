import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { Avatar } from "./Avatar";
import { Portrait } from "./Portrait";
import type { TeamKey } from "./team";
import { TEAM_CLASS } from "./team";
import { Who } from "./Who";

export interface PlayerTileProps {
  name: string;
  tag?: string | null;
  team?: TeamKey | null;
  avatar?: string | null;
  /** Show the hero's portrait instead of the player's picture (after the hero draft). */
  hero?: { name: string; art?: string | null } | null;
  /** The second line: rating, role, status ("Captain", "Ready", "1,512"). */
  line?: ReactNode;
  /** The ready check's tick (true), dimmed while not yet (false). */
  ready?: boolean | null;
  isYou?: boolean;
  /** One control on the right (Pick, Swap). */
  action?: ReactNode;
  /** The element: a list item inside TeamPanel (the default) or a plain block. */
  as?: "li" | "div";
  className?: string;
}

/** A player row: picture, tag and name, a line, an optional action. Your own row is tinted. */
export function PlayerTile({
  name,
  tag,
  team,
  avatar,
  hero,
  line,
  ready = null,
  isYou = false,
  action,
  as: Element = "li",
  className,
}: PlayerTileProps) {
  return (
    <Element
      className={cn(
        "flex min-h-14 items-center gap-3 rounded-row px-3 py-2",
        isYou && (team ? TEAM_CLASS[team].soft : "bg-raised"),
        className,
      )}
    >
      {hero ? (
        <Portrait hero={hero.name} src={hero.art} team={team} />
      ) : (
        <Avatar name={name} src={avatar} team={team} ready={ready} />
      )}
      <span className="flex min-w-0 flex-col">
        <Who name={name} tag={tag} team={team} isYou={isYou} />
        {line ? <span className="text-caption font-medium text-muted">{line}</span> : null}
      </span>
      {action ? <span className="ml-auto shrink-0">{action}</span> : null}
    </Element>
  );
}
