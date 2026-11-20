// /tools/random-draft and /tools/scrims (E06, E07, E08): things for nights outside the queue. The
// random draft rolls every ban and pick and records nothing; scrims are staff's, set up in
// Discord, and their rooms (captain claim, coinflip, hero draft) are the match room's.

import { useLiveMatches, useMe } from "../../api/live";
import { useRandomDraft } from "../../api/queries";
import type { ChampionRef, DraftSide, RandomDraft } from "../../api/types";
import { Button, ButtonLink } from "../../components/Button";
import { InlineAlert } from "../../components/InlineAlert";
import { PageTabs } from "../../components/Navigation";
import { Panel } from "../../components/Layout";
import { Portrait } from "../../components/Portrait";
import { EmptyState, Skeleton } from "../../components/States";
import { TEAM_CLASS } from "../../components/team";
import { errorText, notify } from "../../components/toast";
import { cn } from "../../lib/cn";
import { matchNo, SIDE_NAME, STATUS_LABEL } from "../shared/format";
import { MatchCard } from "../shared/parts";

function Header() {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-4">
      <div className="flex flex-col gap-2">
        <h1 className="text-poster max-md:text-title">Tools</h1>
        <p className="text-body text-muted">Things for nights outside the queue.</p>
      </div>
      <PageTabs
        label="Tools"
        items={[
          { label: "Random draft", to: "/tools/random-draft" },
          { label: "Scrims", to: "/tools/scrims" },
        ]}
      />
    </header>
  );
}

/** The draft as text to paste into Discord. */
export function draftText(draft: RandomDraft): string {
  const names = (heroes: readonly ChampionRef[]) => heroes.map((hero) => hero.name).join(", ") || "none";
  const side = (label: string, part: DraftSide) => `${label}: bans ${names(part.bans)}; picks ${names(part.picks)}`;
  return ["DayShift random draft", side(SIDE_NAME.hk, draft.hk), side(SIDE_NAME.am, draft.am)].join("\n");
}

function SidePanel({ side, part }: { side: "hk" | "am"; part: DraftSide }) {
  return (
    <section aria-labelledby={`${side}-draft`} className={cn("flex min-w-0 flex-1 basis-80 flex-col gap-4 rounded-panel border bg-background p-5", TEAM_CLASS[side].line)}>
      <h3 id={`${side}-draft`} className={cn("text-sheet", TEAM_CLASS[side].text)}>
        {SIDE_NAME[side]}
      </h3>
      <div className="flex flex-col gap-2">
        <span className="text-caption font-extrabold text-muted">Picks</span>
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {part.picks.map((hero) => (
            <li key={hero.id} className="flex items-center gap-2.5">
              <Portrait hero={hero.name} src={hero.icon_url} team={side} size="md" />
              <b className="truncate text-label font-extrabold">{hero.name}</b>
            </li>
          ))}
        </ul>
      </div>
      {part.bans.length ? (
        <p className="text-label text-muted">
          <b className="font-extrabold text-foreground">Bans</b> {part.bans.map((hero) => hero.name).join(", ")}
        </p>
      ) : null}
    </section>
  );
}

export function RandomDraftPage() {
  const roll = useRandomDraft();
  const draft = roll.data;
  return (
    <>
      <Header />
      <Panel as="section" className="flex flex-wrap items-center gap-x-5 gap-y-3 p-6">
        <h2 className="sr-only">Roll a draft</h2>
        <Button
          size="lg"
          icon="dice"
          isPending={roll.isPending}
          pendingLabel="Rolling…"
          onPress={() => roll.mutate()}
        >
          {draft ? "Again" : "Roll a draft"}
        </Button>
        <span className="text-body text-muted">Every ban and pick in the league&apos;s draft order, at random. Nothing is rated or saved.</span>
      </Panel>
      {roll.isError ? <InlineAlert title="That didn't roll">{errorText(roll.error)}</InlineAlert> : null}
      {roll.isPending && !draft ? <Skeleton label="Rolling a draft" lines={3} /> : null}
      {draft ? (
        <section aria-labelledby="draft-heading" aria-live="polite" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="draft-heading" className="text-section">
              Your random draft
            </h2>
            <Button
              kind="ghost"
              icon="copy"
              onPress={() =>
                navigator.clipboard.writeText(draftText(draft)).then(
                  () => notify.success("Copied", "Paste it in Discord."),
                  () => notify.error("Couldn't copy: your browser said no. Select the names instead."),
                )
              }
            >
              Copy
            </Button>
          </div>
          <div className="flex flex-wrap gap-4">
            <SidePanel side="hk" part={draft.hk} />
            <SidePanel side="am" part={draft.am} />
          </div>
          <p className="text-label text-muted">Paste it in Discord and set up the custom game in Deadlock yourselves.</p>
        </section>
      ) : null}
    </>
  );
}

export function ScrimsPage() {
  const me = useMe().data;
  const live = useLiveMatches();
  const scrims = (live.data?.matches ?? []).filter((match) => match.kind === "scrim");
  const mine = me?.scrim ?? null;
  return (
    <>
      <Header />
      <section aria-labelledby="scrims-heading" className="flex flex-col gap-3">
        <h2 id="scrims-heading" className="text-section">
          Scrims
        </h2>
        <p className="max-w-lead text-body text-muted">
          A scrim is two existing teams playing outside the queue. No player draft: each team brings its roster. Staff set one up in Discord; then a
          captain claims each side, the captains flip for sides and draft heroes like any match. Scrims are unrated.
        </p>
      </section>
      {mine ? (
        <section aria-label="Your scrim" className="flex flex-wrap items-center justify-between gap-4 rounded-panel border-2 border-foreground bg-surface px-6 py-5">
          <span className="flex flex-col gap-1">
            <span className="text-label font-bold text-muted">Your scrim</span>
            <b className="type-display text-section">
              {matchNo(mine.id)} · {STATUS_LABEL[mine.status]}
            </b>
            <span className="text-label text-muted">
              {mine.status === "captain_claim" ? "Claim captain for your side from its room." : mine.is_captain ? "You're a captain." : "You're on its roster."}
            </span>
          </span>
          <ButtonLink to={`/matches/${mine.id}`} size="lg" icon="next">
            Open the room
          </ButtonLink>
        </section>
      ) : null}
      {live.state === "loading" ? (
        <Skeleton label="Loading scrims" lines={2} avatar={false} />
      ) : scrims.length === 0 ? (
        <EmptyState title="No scrims right now">When staff start one in Discord, it shows here and anyone can watch its draft.</EmptyState>
      ) : (
        <ul className="flex flex-col gap-2.5">
          {scrims.map((scrim) => (
            <li key={scrim.id}>
              <MatchCard id={scrim.id} status={scrim.status} captains={scrim.captains} sides={scrim.sides} line={`${scrim.draft_name} · scrim, unrated`} played={scrim.id === mine?.id} />
            </li>
          ))}
        </ul>
      )}
      <p className="text-label text-muted">Sides take their colours at the coinflip: until then neither team is The Hidden King or The Archmother.</p>
    </>
  );
}
