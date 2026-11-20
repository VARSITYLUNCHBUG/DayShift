// /link-steam (A03, A09): your Steam links and what each state means. Every account you've linked
// is listed with its own state and Unlink; Link with Steam proves one on Steam's own page.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

import { queries } from "../../api/queries";
import { linkSteamUrl } from "../../api/session";
import type { SteamRow } from "../../api/types";
import { Button, ButtonLink } from "../../components/Button";
import { Icon } from "../../components/Icon";
import { PageHeader, Panel } from "../../components/Layout";
import { ErrorState, Skeleton } from "../../components/States";
import { Sticker } from "../../components/Sticker";
import { cn } from "../../lib/cn";
import { shortDate } from "../../lib/format";
import { BackLink } from "../shared/parts";
import { UnlinkDialog } from "./UnlinkDialog";

export type SteamState = "none" | "claimed" | "proven";

/** A link is proven once you signed in through Steam, or the bot saw it on your team. */
export function steamState(row: SteamRow): Exclude<SteamState, "none"> {
  return row.proven || row.verified ? "proven" : "claimed";
}

export function SteamStatus({ row }: { row: SteamRow }) {
  return steamState(row) === "proven" ? (
    <span className="inline-flex items-center gap-1.5 text-caption font-extrabold text-ok">
      <Icon name="check" size={16} />
      Proven
    </span>
  ) : (
    <Sticker tone="raised" size="sm">
      Not proven
    </Sticker>
  );
}

const STATES: { id: SteamState; title: string; badge: ReactNode; body: string }[] = [
  {
    id: "none",
    title: "Not linked",
    badge: (
      <Sticker tone="raised" size="sm">
        Not linked
      </Sticker>
    ),
    body: "No Steam account on your profile. Results still count; your stats just can't be matched to you.",
  },
  {
    id: "claimed",
    title: "Linked, not proven",
    badge: (
      <Sticker tone="raised" size="sm">
        Not proven
      </Sticker>
    ),
    body: "Someone claimed this Steam account by typing its ID (with /link in Discord). It isn't proven, so if it's yours, Link with Steam proves you own it and takes it over.",
  },
  {
    id: "proven",
    title: "Proven",
    badge: (
      <span className="inline-flex items-center gap-1.5 text-caption font-extrabold text-ok">
        <Icon name="check" size={16} />
        Proven
      </span>
    ),
    body: "You signed in on Steam's own page, so it's proven yours. Nobody else can claim it, and Sign in with Steam works for you.",
  },
];

function Accounts({ steam, discordName, onUnlink }: { steam: readonly SteamRow[]; discordName: string; onUnlink: (row: SteamRow) => void }) {
  const link = (
    <ButtonLink to={linkSteamUrl("/link-steam")} external icon="steam" size="lg" kind={steam.length ? "ghost" : "primary"}>
      {steam.length ? "Link another account" : "Link with Steam"}
    </ButtonLink>
  );
  return (
    <Panel as="section" className="flex flex-col gap-4 p-6">
      <h2 className="sr-only">Your Steam accounts</h2>
      {steam.length === 0 ? (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
          <div className="flex min-w-0 flex-1 basis-75 items-center gap-3.5">
            <span aria-hidden="true" className="flex size-14 shrink-0 items-center justify-center rounded-full border-2 border-dashed border-line-strong text-muted">
              <Icon name="steam" size={26} />
            </span>
            <span className="flex flex-col gap-0.5">
              <b className="text-lead font-extrabold">No Steam account linked</b>
              <span className="text-label text-muted">Discord: {discordName} · signed in</span>
            </span>
          </div>
          {link}
        </div>
      ) : (
        <>
          <ul className="flex flex-col gap-2.5">
            {steam.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-card border border-line bg-background px-4 py-3">
                <span className="text-muted">
                  <Icon name="steam" size={22} />
                </span>
                <span className="flex min-w-0 flex-1 basis-50 flex-col">
                  <b className="truncate text-body font-extrabold">{row.name || "Steam account"}</b>
                  <span className="text-caption text-muted">
                    {steamState(row) === "proven" ? "Proven · results and sign-in" : "Claimed · results only"} · linked {shortDate(row.linked_at)}
                  </span>
                </span>
                <SteamStatus row={row} />
                <Button kind="danger" size="sm" onPress={() => onUnlink(row)} aria-label={`Unlink ${row.name || "this Steam account"}`}>
                  Unlink
                </Button>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-3">{link}</div>
        </>
      )}
      <p className="text-label text-muted">
        You sign in on Steam&apos;s own page and come back here. We get your Steam ID and name, never your password.
      </p>
    </Panel>
  );
}

export function LinkSteamPage() {
  const me = useQuery(queries.me(null));
  const [unlinking, setUnlinking] = useState<SteamRow | null>(null);
  const steam = me.data?.accounts.steam ?? [];
  const current: SteamState = steam.length === 0 ? "none" : steam.some((row) => steamState(row) === "proven") ? "proven" : "claimed";

  return (
    <div className="flex flex-wrap items-start gap-x-10 gap-y-8">
      <div className="flex min-w-0 flex-999 basis-160 flex-col gap-6">
        <BackLink to="/me">Me</BackLink>
        <PageHeader title="Link Steam" />
        <ul className="flex max-w-lead flex-col gap-4">
          {[
            { icon: "search" as const, title: "Your results find you", line: "We match Deadlock match results and scoreboard names to your Steam account, so your numbers land on your page without anyone mapping names." },
            { icon: "steam" as const, title: "Sign in with Steam", line: "Once linked, the Steam button on the sign-in page works for you too." },
          ].map((item) => (
            <li key={item.title} className="flex items-start gap-3.5">
              <span aria-hidden="true" className="flex size-11 shrink-0 items-center justify-center rounded-full bg-raised">
                <Icon name={item.icon} size={20} />
              </span>
              <span className="flex flex-col gap-0.5">
                <b className="text-body font-extrabold">{item.title}</b>
                <span className="text-body text-muted">{item.line}</span>
              </span>
            </li>
          ))}
        </ul>
        {me.isPending ? (
          <Skeleton label="Loading your Steam accounts" lines={2} />
        ) : me.isError ? (
          <ErrorState
            title="We can't load your accounts right now"
            action={
              <Button kind="ghost" onPress={() => void me.refetch()}>
                Try again
              </Button>
            }
          >
            Nothing has changed on your profile. Try again in a moment.
          </ErrorState>
        ) : (
          <Accounts steam={steam} discordName={me.data.accounts.discord_name} onUnlink={setUnlinking} />
        )}
      </div>
      <section aria-labelledby="states-heading" className="flex min-w-0 flex-1 basis-90 flex-col gap-3.5 pt-2">
        <h2 id="states-heading" className="text-section">
          What the states mean
        </h2>
        <ul className="flex flex-col gap-2.5">
          {STATES.map((state) => {
            const here = !me.isPending && state.id === current;
            return (
              <li
                key={state.id}
                aria-current={here ? "true" : undefined}
                className={cn("flex flex-col gap-2 rounded-panel border-2 p-5", here ? "border-foreground bg-raised" : "border-line bg-surface")}
              >
                <span className="flex items-center justify-between gap-2">
                  <b className="text-body font-extrabold">{state.title}</b>
                  {state.badge}
                </span>
                <span className="text-label text-muted">{state.body}</span>
                {here ? <b className="text-caption font-extrabold">You are here</b> : null}
                {state.id === "claimed" ? (
                  <details className="text-label">
                    <summary className="min-h-11 cursor-pointer content-center font-extrabold underline underline-offset-2">If someone else proves it first</summary>
                    <span className="text-muted">
                      A proven owner always replaces an unproven claim: if another Discord account signs in with Steam as that account, their link
                      replaces yours. Your past results stay on your page. A proven link is never replaced by a claim; only staff can move it.
                    </span>
                  </details>
                ) : null}
              </li>
            );
          })}
        </ul>
      </section>
      <UnlinkDialog account={unlinking} onClose={() => setUnlinking(null)} />
    </div>
  );
}

export default LinkSteamPage;
