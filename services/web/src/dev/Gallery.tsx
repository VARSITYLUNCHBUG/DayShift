// /dev/screens (development builds only): the DayShift components in dark and light, the two
// shells, and the old screens rendered from Django's fixtures.
import { lazy, Suspense, useState } from "react";
import type { ReactNode } from "react";
import { Link, Route, Routes } from "react-router";

import { Avatar } from "../components/Avatar";
import { Banner } from "../components/Banner";
import { Lockup, Mark } from "../components/Brand";
import { Button, ButtonLink, IconButton } from "../components/Button";
import { Countdown } from "../components/Countdown";
import { Bar, DataTable, ScoreLine, StackedBar, StatTile } from "../components/Data";
import { Dialog } from "../components/Dialog";
import { DraftStrip } from "../components/DraftStrip";
import { HeroCard } from "../components/HeroCard";
import { HeroGrid } from "../components/HeroGrid";
import { Icon, ICON_NAMES } from "../components/Icon";
import { InlineAlert } from "../components/InlineAlert";
import { Panel, Section } from "../components/Layout";
import { LeadChart } from "../components/LeadChart";
import { LobbyCode } from "../components/LobbyCode";
import { PageTabs, Segmented, StatusChip } from "../components/Navigation";
import { NoticeSheet } from "../components/NoticeSheet";
import { PlayerGrid } from "../components/PlayerGrid";
import { PlayerTile } from "../components/PlayerTile";
import { Portrait } from "../components/Portrait";
import { Scorebug, TeamBlock, TurnBanner } from "../components/Scorebug";
import { AppShell } from "../components/shell/AppShell";
import { RANKED_PHASES } from "../components/shell/RoomHeader";
import { RoomShell } from "../components/shell/RoomShell";
import { ThemeSwitch } from "../components/shell/TopBar";
import { EmptyState, ErrorState, Skeleton } from "../components/States";
import { Badge, Sticker, Tag } from "../components/Sticker";
import { TeamPanel } from "../components/TeamPanel";
import { notify } from "../components/toast";
import { Who } from "../components/Who";
import { AM_PLAYERS, DRAFT_STEPS, heroArt, heroChoices, HK_PLAYERS, MATCH_NO, ME, NIGHT, SOUL_LEAD, inSeconds } from "./sample";

const LegacyGallery = lazy(() => import("../legacy/dev/ScreenGallery"));

function Spec({ label, children, note }: { label: string; children: ReactNode; note?: string }) {
  return (
    <figure className="m-0 flex min-w-0 flex-col gap-2.5">
      <div className="flex min-h-16 flex-wrap items-center gap-3 rounded-card border border-dashed border-line bg-surface p-5">{children}</div>
      <figcaption className="flex flex-col gap-0.5">
        <b className="text-caption font-extrabold">{label}</b>
        {note ? <span className="text-caption text-muted">{note}</span> : null}
      </figcaption>
    </figure>
  );
}

function Grid({ children, cols = "md:grid-cols-2 xl:grid-cols-3" }: { children: ReactNode; cols?: string }) {
  return <div className={`grid grid-cols-1 gap-4 ${cols}`}>{children}</div>;
}

function Sheet() {
  const [hero, setHero] = useState<string | null>("Ivy");
  const [player, setPlayer] = useState<string | null>(null);
  const [view, setView] = useState<"summary" | "timeline">("summary");
  const [dialog, setDialog] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [pending, setPending] = useState(false);
  const deadline = inSeconds(27);

  return (
    <div className="flex flex-col gap-10">
      <Section title="Brand">
        <Grid>
          <Spec label="Lockup" note="Top bar, 24px; the wordmark follows the text colour.">
            <Lockup size={32} />
          </Spec>
          <Spec label="Mark" note="The favicon and the room header's way back to Play.">
            <Mark size={40} />
            <Mark size={20} />
          </Spec>
          <Spec label="Icons" note="docs/assets/brand/icons, 24 grid, 2px round strokes.">
            {ICON_NAMES.map((name) => (
              <span key={name} title={name} className="text-muted">
                <Icon name={name} />
              </span>
            ))}
          </Spec>
        </Grid>
      </Section>

      <Section title="Buttons">
        <Grid>
          <Spec label="Primary · cream on ink" note="The one main action.">
            <Button>Queue up</Button>
            <Button size="lg">I&apos;m ready</Button>
          </Spec>
          <Spec label="Team turn" note="The acting team's fill; only the acting captain gets it.">
            <Button team="hk">Lock in Ivy</Button>
            <Button team="am">Ban Kelvin</Button>
          </Spec>
          <Spec label="Ghost, quiet, secondary">
            <Button kind="ghost">Need a sub</Button>
            <Button kind="quiet">Not now</Button>
            <Button kind="secondary">Send</Button>
          </Spec>
          <Spec label="Danger" note="Outlined; solid only to confirm.">
            <Button kind="danger">Leave the queue</Button>
            <Button kind="danger-solid">Dispute the result</Button>
          </Spec>
          <Spec label="Pending and disabled" note="Keeps its place and can&apos;t be pressed twice.">
            <Button
              team="hk"
              isPending={pending}
              pendingLabel="Locking in Ivy…"
              onPress={() => {
                setPending(true);
                setTimeout(() => setPending(false), 2000);
              }}
            >
              Lock in Ivy
            </Button>
            <Button isDisabled>Lock in</Button>
          </Spec>
          <Spec label="Icon button and link">
            <IconButton icon="copy" label="Copy the lobby code" />
            <IconButton icon="close" label="Dismiss" kind="quiet" />
            <ButtonLink to="/dev/screens/room" kind="ghost" icon="next">
              Open the room
            </ButtonLink>
          </Spec>
        </Grid>
      </Section>

      <Section title="Stickers, tags and who">
        <Grid>
          <Spec label="Stickers" note="Tilted pills with the hard drop. Bubblegum is DayShift's own moment.">
            <Sticker>Doors open</Sticker>
            <Sticker tone="danger">Banned</Sticker>
            <Sticker tone="hk">Won</Sticker>
            <Sticker tone="cream">GG</Sticker>
            <Badge label="3 unread">3</Badge>
          </Spec>
          <Spec label="Clan tags" note="Team colour inside a match, neutral outside.">
            <Tag team="hk">OWL</Tag>
            <Tag team="am">MSN</Tag>
            <Tag>KRK</Tag>
          </Spec>
          <Spec label="Who">
            <Who name={ME} tag="OWL" team="hk" isYou />
            <Who name="Vesper" tag="MSN" team="am" />
          </Spec>
        </Grid>
      </Section>

      <Section title="Avatars, portraits and hero cards">
        <Grid>
          <Spec label="Avatar" note="Initials while there's no picture; a tick for ready.">
            <Avatar name="Rook" />
            <Avatar name="Pike" team="hk" ready />
            <Avatar name="Vesper" team="am" ready={false} />
          </Spec>
          <Spec label="Portrait" note="Team ring; a cream halo for you; dead on the map.">
            <Portrait hero="Ivy" src={heroArt("Ivy")} team="hk" />
            <Portrait hero="Dynamo" src={heroArt("Dynamo")} team="am" isYou />
            <Portrait hero="Haze" src={heroArt("Haze")} team="am" isDead />
          </Spec>
          <Spec label="Hero cards" note="free · selected · banned · taken · locked">
            <div className="grid w-full grid-cols-5 gap-2">
              <HeroCard name="Mirage" art={heroArt("Mirage")} wishes="QL" tag="Quill wants him" />
              <HeroCard name="Ivy" art={heroArt("Ivy")} state="selected" tag="Selected" />
              <HeroCard name="Haze" art={heroArt("Haze")} state="banned" />
              <HeroCard name="Dynamo" art={heroArt("Dynamo")} state="am" tag="Vesper's Team" tagTone="am" />
              <HeroCard name="Abrams" art={heroArt("Abrams")} state="locked" tag="Locked" tagTone="hk" />
            </div>
          </Spec>
        </Grid>
        <Spec label="Hero grid" note="One Tab stop; arrows move, Enter or Space selects.">
          <div className="w-full">
            <HeroGrid heroes={heroChoices()} selectedId={hero} onSelect={setHero} />
          </div>
        </Spec>
      </Section>

      <Section title="Players and teams">
        <Grid cols="lg:grid-cols-2">
          <TeamPanel
            team="hk"
            name="Rook's Team"
            players={HK_PLAYERS.map((p) => ({ id: p.id, name: p.name, tag: p.tag, isYou: p.name === ME, line: p.name === ME ? "Captain" : undefined }))}
          />
          <TeamPanel
            team="am"
            name="Vesper's Team"
            players={AM_PLAYERS.map((p) => ({ id: p.id, name: p.name, tag: p.tag, hero: { name: p.hero, art: heroArt(p.hero) } }))}
          />
        </Grid>
        <Spec label="Player tile with an action">
          <ul className="w-full">
            <PlayerTile name="Mothball" tag="KRK" line="1,388 · Gold" action={<Button size="sm">Pick Mothball</Button>} />
          </ul>
        </Spec>
        <Spec label="Player grid" note="The player draft's pick grid.">
          <div className="w-full">
            <PlayerGrid
              players={[...HK_PLAYERS.slice(2), ...AM_PLAYERS.slice(2)].map((p, i) => ({ id: p.id, name: p.name, tag: p.tag, line: `${1500 - i * 37} · Gold`, isTaken: i === 1 }))}
              selectedId={player}
              onSelect={setPlayer}
            />
          </div>
        </Spec>
      </Section>

      <Section title="Match room parts">
        <div className="overflow-hidden rounded-panel border border-line">
          <Scorebug
            left={<TeamBlock team="hk" name="Rook's Team" line="Captain Rook" isActing />}
            right={<TeamBlock team="am" name="Vesper's Team" line="Captain Vesper" align="end" />}
            deadline={deadline}
            tone="hk"
            title="Your pick, Rook"
            line="Pick 4 of 12 · then Vesper picks twice · runs out: a random hero"
            action={
              <>
                <Button kind="ghost" icon="dice">
                  Random
                </Button>
                <Button team="hk">Lock in Ivy</Button>
              </>
            }
          />
        </div>
        <Grid cols="lg:grid-cols-2">
          <TurnBanner deadline={deadline} tone="hk" title="Your pick" line="Pick 4 of 12 · then Vesper" action={<Button team="hk" size="sm">Lock in Ivy</Button>} />
          <TurnBanner deadline={inSeconds(19)} tone="am" title="Vesper's pick" line="You're next: pick 4 of 12" />
          <TurnBanner deadline={inSeconds(-1)} title="Waiting for the server" line="Your pick is in" />
          <Spec label="Countdowns" note="role=timer; counts to the server's deadline; never below 0:00.">
            <Countdown deadline={inSeconds(45)} size="dialog" />
            <Countdown deadline={inSeconds(272)} />
            <Countdown deadline={inSeconds(-5)} />
          </Spec>
        </Grid>
        <Spec label="Draft strip" note="Step 8 on the clock; bans struck through.">
          <div className="w-full">
            <DraftStrip steps={DRAFT_STEPS} current={7} />
          </div>
        </Spec>
        <Spec label="Lobby code" note="Read letter by letter; shown to the 12 players only.">
          <LobbyCode code="K7Q2PX" />
        </Spec>
      </Section>

      <Section title="Notices">
        <Grid>
          <Spec label="Toast" note="Bottom-left, 8 s, pauses on hover and focus.">
            <Button kind="ghost" onPress={() => notify.info("You're in", "8 of 12 in the queue")}>
              Show a toast
            </Button>
            <Button kind="ghost" onPress={() => notify.error(new Error("Only captains can report the result."))}>
              Show a refusal
            </Button>
          </Spec>
          <Spec label="Dialog" note="Must answer now: traps focus, no Esc.">
            <Button onPress={() => setDialog(true)}>Open Ready Up</Button>
          </Spec>
          <Spec label="Sheet" note="Answer soon: not modal, focus goes to its heading.">
            <Button onPress={() => setSheet(true)}>Offer a spot</Button>
          </Spec>
        </Grid>
        <Banner kind="warn">Reconnecting. Your place and picks are safe. Trying again…</Banner>
        <Banner kind="info" action={<Button kind="ghost" size="sm">Watch</Button>}>
          Match paused for a sub. Brindle&apos;s spot is being filled.
        </Banner>
        <Grid cols="lg:grid-cols-2">
          <InlineAlert title="That code didn't work" action={<Button kind="ghost" size="sm">Try again</Button>}>
            Deadlock says there&apos;s no lobby K7Q2PX. Check the code in the game and try again.
          </InlineAlert>
          <InlineAlert kind="info" title="Lobby codes are 6 letters and numbers">
            This one has 5.
          </InlineAlert>
        </Grid>
        <Dialog
          isOpen={dialog}
          mustAnswer
          eyebrow={`${MATCH_NO} · ${NIGHT}`}
          title="Doors open"
          deadline={inSeconds(45)}
          announce="to ready up"
          actions={
            <>
              <Button size="lg" autoFocus onPress={() => setDialog(false)}>
                I&apos;m ready
              </Button>
              <Button kind="quiet" onPress={() => setDialog(false)}>
                Can&apos;t make it
              </Button>
            </>
          }
        >
          Twelve in. Ready up and we&apos;re off. Miss it and you&apos;re out of this match with a strike.
        </Dialog>
        <NoticeSheet
          isOpen={sheet}
          eyebrow="Spot offered"
          title="A spot's open in No. 413"
          deadline={inSeconds(45)}
          tone="am"
          onDismiss={() => setSheet(false)}
          actions={
            <>
              <Button onPress={() => setSheet(false)}>Take the spot</Button>
              <Button kind="quiet" onPress={() => setSheet(false)}>
                Not now
              </Button>
            </>
          }
        >
          Brindle had to go. Take their place on Vesper&apos;s Team; the match is paused for you.
        </NoticeSheet>
      </Section>

      <Section title="Empty, loading and error">
        <Grid>
          <EmptyState title="No matches tonight yet" action={<Button kind="ghost">Join the queue</Button>}>
            The first one starts when 12 are in the queue.
          </EmptyState>
          <Panel>
            <Skeleton />
          </Panel>
          <ErrorState title="We couldn't save your wishes" action={<Button kind="ghost">Try again</Button>}>
            The connection dropped while saving. Your list is still here; try again.
          </ErrorState>
        </Grid>
      </Section>

      <Section title="Tables and stats">
        <Grid cols="md:grid-cols-4">
          <StatTile label="Your rating" value="1,512" line="+17 tonight" />
          <StatTile label="Ladder" value="#14" line="▲ 4 this week" />
          <ScoreLine label="Kills" hk="41" am="27" />
          <ScoreLine label="Souls" hk="251k" am="230k" />
        </Grid>
        <DataTable
          caption="Rook's Team scoreboard"
          rowKey={(row) => row.id}
          rows={HK_PLAYERS}
          highlight={(row) => row.name === ME}
          columns={[
            { key: "player", header: "Player", isRowHeader: true, cell: (row) => <Who name={row.name} tag={row.tag} team="hk" isYou={row.name === ME} /> },
            { key: "hero", header: "Hero", cell: (row) => row.hero },
            { key: "kills", header: "Kills", align: "right", cell: (row) => (Number(row.id) * 7) % 13 },
            { key: "souls", header: "Souls", align: "right", cell: (row) => (39_880 + Number(row.id) * 1_337).toLocaleString("en-GB") },
          ]}
        />
        <Grid cols="lg:grid-cols-2">
          <Spec label="Bars">
            <div className="flex w-full flex-col gap-3">
              <Bar value={39} max={50} tone="hk" />
              <Bar value={27} max={50} tone="am" />
              <StackedBar parts={[{ share: 0.52, tone: "hk" }, { share: 0.48, tone: "am" }]} />
            </div>
          </Spec>
          <Spec label="Lead chart" note="Amber above when The Hidden King leads, blue below.">
            <LeadChart points={SOUL_LEAD} label="Souls lead over 31:12. Rook's Team led from about 9:00." className="h-40 w-full" />
          </Spec>
        </Grid>
      </Section>

      <Section title="Navigation">
        <Grid>
          <Spec label="Status chip">
            <StatusChip to="/dev/screens/app" live>
              In the queue · 8/12
            </StatusChip>
            <StatusChip tone="hk" live>
              No. 413 · Your pick 0:27
            </StatusChip>
          </Spec>
          <Spec label="Page tabs" note="Real links; the current one is bubblegum.">
            <PageTabs
              label="Postgame"
              items={[
                { label: "Summary", to: "/dev/screens", end: true },
                { label: "Timeline", to: "/dev/screens/timeline" },
                { label: "Replay", to: "/dev/screens/replay" },
              ]}
            />
          </Spec>
          <Spec label="Segmented">
            <Segmented
              label="View"
              value={view}
              onChange={setView}
              options={[
                { id: "summary", label: "Summary" },
                { id: "timeline", label: "Timeline" },
              ]}
            />
          </Spec>
        </Grid>
      </Section>
    </div>
  );
}

type Mode = "both" | "dark" | "light";

function Index() {
  const [mode, setMode] = useState<Mode>("both");
  const themes = mode === "both" ? (["dark", "light"] as const) : ([mode] as const);
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="flex flex-wrap items-center gap-4 border-b border-line px-8 py-3">
        <Lockup size={22} />
        <span className="text-label font-bold text-muted">· Components · development only</span>
        <nav aria-label="Gallery" className="ml-auto flex flex-wrap items-center gap-2">
          <ButtonLink to="/dev/screens/app" kind="ghost" size="sm">
            App shell
          </ButtonLink>
          <ButtonLink to="/dev/screens/room" kind="ghost" size="sm">
            Room shell
          </ButtonLink>
          <ButtonLink to="/dev/screens/legacy" kind="ghost" size="sm">
            Old screens
          </ButtonLink>
          <Segmented
            label="Theme"
            value={mode}
            onChange={setMode}
            options={[
              { id: "both", label: "Both" },
              { id: "dark", label: "Dark" },
              { id: "light", label: "Light" },
            ]}
          />
        </nav>
      </header>
      <main id="main" className={`grid flex-1 grid-cols-1 ${themes.length === 2 ? "2xl:grid-cols-2" : ""}`}>
        {themes.map((theme) => (
          <div key={theme} data-theme={theme} className={`${theme} min-w-0 bg-background px-8 py-10 text-foreground`}>
            <h1 className="mb-8 text-board">{theme === "dark" ? "Dark" : "Light"}</h1>
            <Sheet />
          </div>
        ))}
      </main>
    </div>
  );
}

function AppPreview() {
  return (
    <AppShell me={{ name: ME }} status={<StatusChip to="/dev/screens/app" live>In the queue · 8/12</StatusChip>}>
      <header className="flex flex-col gap-3">
        <span className="text-label font-bold text-muted">{NIGHT}</span>
        <h1 className="text-poster max-md:text-title">You&apos;re in. 4 more to go.</h1>
        <p className="max-w-lead text-lead text-muted">When the twelfth seat fills, doors open here and in Discord.</p>
      </header>
      <div className="flex flex-wrap gap-2.5">
        <Button kind="danger">Leave the queue</Button>
        <ThemeSwitch />
        <Link to="/dev/screens" className="link self-center">
          Back to the components
        </Link>
      </div>
      <EmptyState title="No matches tonight yet">The first one starts when 12 are in the queue.</EmptyState>
    </AppShell>
  );
}

function RoomPreview() {
  const [hero, setHero] = useState<string | null>("Ivy");
  const deadline = inSeconds(27);
  return (
    <RoomShell
      number={MATCH_NO}
      title={NIGHT}
      phases={RANKED_PHASES}
      current={4}
      tone="hk"
      phaseLine="Heroes · your pick"
      deadline={deadline}
      me={{ name: ME }}
      actions={<Button kind="ghost" size="sm">Need a sub</Button>}
      bug={
        <Scorebug
          left={<TeamBlock team="hk" name="Rook's Team" line="Captain Rook" isActing />}
          right={<TeamBlock team="am" name="Vesper's Team" line="Captain Vesper" align="end" />}
          deadline={deadline}
          tone="hk"
          title="Your pick, Rook"
          line="Pick 4 of 12 · then Vesper picks twice · runs out: a random hero"
          announce="to pick"
          action={<Button team="hk">Lock in {hero ?? "a hero"}</Button>}
        />
      }
      phoneBug={<TurnBanner deadline={deadline} tone="hk" title="Your pick" line="Pick 4 of 12 · then Vesper" announce="to pick" />}
      footer={
        <>
          <Button kind="ghost" icon="dice">
            Random
          </Button>
          <Button team="hk">Lock in {hero ?? "a hero"}</Button>
        </>
      }
      rail={
        <Panel as="section">
          <h2 className="text-card">Team chat</h2>
          <p className="text-caption text-muted">Only Rook&apos;s Team</p>
        </Panel>
      }
    >
      <DraftStrip steps={DRAFT_STEPS} current={7} />
      <HeroGrid heroes={heroChoices()} selectedId={hero} onSelect={setHero} />
    </RoomShell>
  );
}

export default function Gallery() {
  return (
    <Routes>
      <Route index element={<Index />} />
      <Route path="app" element={<AppPreview />} />
      <Route path="room" element={<RoomPreview />} />
      <Route
        path="legacy/*"
        element={
          <Suspense>
            <LegacyGallery />
          </Suspense>
        }
      />
      <Route path="*" element={<Index />} />
    </Routes>
  );
}
