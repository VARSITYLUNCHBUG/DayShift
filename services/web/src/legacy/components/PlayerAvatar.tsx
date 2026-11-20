import { Avatar } from "@heroui/react";

import { initials } from "../lib/format";

interface Props {
  name: string;
  url: string | null;
  size?: "sm" | "md" | "lg";
  className?: string;
}

/** A Discord avatar, or the player's initials when there's none (or it fails to load). */
export function PlayerAvatar({ name, url, size = "sm", className }: Props) {
  return (
    <Avatar size={size} color="accent" variant="soft" className={className}>
      {url ? <Avatar.Image alt="" src={url} /> : null}
      <Avatar.Fallback>{initials(name)}</Avatar.Fallback>
    </Avatar>
  );
}
