import { Card, Chip, Skeleton } from "@heroui/react";

import { linkSteamUrl } from "../../api/session";
import { AppShell } from "../components/AppShell";
import { ButtonLink } from "../components/ButtonLink";
import { PlayerAvatar } from "../components/PlayerAvatar";
import { initials } from "../lib/format";
import { useTopic } from "../../live/hooks";
import type { MePlayer } from "../../live/types";

/** 1.3: the step before Steam. Steam's answer links the account straight away (decision D4),
 * so this page says what's about to happen, and Link goes to Steam. */
export function LinkSteamPage() {
  const { data: me } = useTopic("me");
  return (
    <AppShell>
      <div className="flex justify-center">
        {me ? <LinkSteamView player={me.player} /> : <Skeleton className="h-100 w-full max-w-120 rounded-3xl" />}
      </div>
    </AppShell>
  );
}

export function LinkSteamView({ player }: { player: MePlayer }) {
  const steam = player.steam;
  return (
    <Card className="w-full max-w-120 gap-5 rounded-3xl border border-border p-7">
      <h1 className="text-2xl font-bold">Link Steam</h1>
      {steam.linked && steam.name ? (
        <div className="flex items-center gap-3.5 rounded-2xl border border-border bg-background p-4">
          <span className="flex size-14 items-center justify-center rounded-2xl border border-default bg-steam text-lg font-bold text-steam-foreground">
            {initials(steam.name)}
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="truncate text-lg font-semibold">{steam.name}</span>
            {steam.verified || steam.proven ? (
              <Chip size="sm" color="success" variant="soft" className="self-start font-semibold">
                {steam.verified ? "Steam verified" : "Linked"}
              </Chip>
            ) : null}
          </span>
        </div>
      ) : null}
      <div className="flex items-center gap-2.5 text-sm text-muted">
        <PlayerAvatar name={player.name} url={player.avatar_url} />
        <span>
          to <b className="text-foreground">{player.name}</b> on Discord
        </span>
      </div>
      <div className="mt-auto flex gap-2.5">
        <ButtonLink to="/" variant="outline" size="lg" className="h-12 flex-1 font-semibold">
          Cancel
        </ButtonLink>
        <ButtonLink to={linkSteamUrl("/link-steam")} external size="lg" className="h-12 flex-1 font-semibold">
          Link
        </ButtonLink>
      </div>
    </Card>
  );
}
