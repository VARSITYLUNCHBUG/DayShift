// /dev/screens (development builds only): every screen, rendered from the fixtures Django
// writes, for comparing against the design boards. Each entry runs on its own FakeServer.
import { Card, Chip } from "@heroui/react";
import { Fragment, useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { Link, Route, Routes, useParams } from "react-router";

import { AppShell } from "../components/AppShell";
import { ButtonLink } from "../components/ButtonLink";
import { notify } from "../components/toast";
import type { MatchSnap, MeSnap, QueueSnap, LiveSnap } from "../../live/types";
import { matchTopic } from "../../live/types";
import { LinkSteamView } from "../screens/LinkSteam";
import { DisputeDialog } from "../screens/match/Confirm";
import { EarlyLeaveDialog } from "../screens/match/EarlyLeave";
import { MatchView } from "../screens/match/MatchRoute";
import { ReportDialog } from "../screens/match/ReportDialog";
import { listed, MatchesView } from "../screens/matches/Matches";
import type { MatchFilter } from "../screens/matches/Matches";
import { PastMatchView } from "../screens/matches/PastMatch";
import { PlayView } from "../screens/play/Play";
import { ReadyUpView } from "../screens/ReadyUpDialog";
import { REFUSALS } from "../screens/signin/refusals";
import { SignInView } from "../screens/signin/SignIn";
import { LeaderboardView } from "../screens/stats/LeaderboardPage";
import { ProfileView } from "../screens/stats/ProfilePage";
import { RandomDraftView } from "../screens/tools/RandomDraftPage";
import { OfferDialog } from "../screens/subs/OfferDialog";
import { SubNameDialog } from "../screens/subs/SubNameDialog";
import { SubRequestDialog } from "../screens/subs/SubRequestDialog";
import {
  apiLobbyMatch,
  autoCaptainMe,
  fixture,
  has,
  http,
  ineligibleVoteMatch,
  inMatchMe,
  matchList,
  needSubMatch,
  placeHeldMe,
  recordedMatch,
  SCENARIOS,
  seasonLeaderboard,
  seasonProfile,
  subOptions,
  VIEWS,
  waitingDraft,
} from "./fixtures";
import type { MatchView as View } from "./fixtures";
import { ComponentSheet } from "./ComponentSheet";
import { HttpPreview } from "./HttpPreview";
import { LivePreview } from "./LivePreview";

interface Entry {
  id: string;
  group: string;
  title: string;
  /** Where it comes from: a fixture name, or "derived from …" when changed for the screen. */
  source: string;
  render: () => ReactNode;
}

function play(me: MeSnap, queue: QueueSnap, live: LiveSnap): ReactNode {
  return (
    <LivePreview snaps={{ me, queue, live }} playerId={me.player.id}>
      <AppShell>
        <PlayView me={me} queue={queue} live={live} />
      </AppShell>
    </LivePreview>
  );
}

function matchPage(match: MatchSnap, me: MeSnap): ReactNode {
  // The result screen adds the match's record over HTTP.
  const answers: [string[], unknown][] = match.status === "completed" ? [[["matches", match.id], recordedMatch()]] : [];
  return (
    <HttpPreview answers={answers}>
      <LivePreview snaps={{ me, [matchTopic(match.id)]: match }} playerId={me.player.id}>
        <MatchView match={match} />
      </LivePreview>
    </HttpPreview>
  );
}

/** A signed-in page (top bar and all) as P3, the finished match's player. */
function page(body: ReactNode): ReactNode {
  const me = fixture.me("completed", "player");
  return (
    <LivePreview snaps={{ me }} playerId={me.player.id}>
      <AppShell>{body}</AppShell>
    </LivePreview>
  );
}

function notReady(match: MatchSnap, playerId: string): MatchSnap {
  return { ...match, players: match.players.map((p) => (p.id === playerId ? { ...p, is_ready: false } : p)) };
}

function entries(): Entry[] {
  const list: Entry[] = [];
  const signIn = "1 Sign in and queue";
  list.push({
    id: "signin",
    group: signIn,
    title: "1.1 Sign in",
    source: "no data",
    render: () => <SignInView error={null} next="/" devLogin />,
  });
  for (const code of Object.keys(REFUSALS)) {
    list.push({
      id: `signin-${code}`,
      group: signIn,
      title: `1.2 Sign-in refused: ${code}`,
      source: `/signin?error=${code}`,
      render: () => <SignInView error={code} next="/" devLogin={false} />,
    });
  }
  const unlinked = fixture.me("completed", "player");
  const linked: MeSnap = {
    ...unlinked,
    player: { ...unlinked.player, steam: { linked: true, proven: false, verified: false, name: "RookPlays" } },
  };
  for (const [id, me, source] of [
    ["link-steam", unlinked, "completed.me-player"],
    ["link-steam-claimed", linked, "derived from completed.me-player: an unproven Steam claim"],
  ] as const) {
    list.push({
      id,
      group: signIn,
      title: `1.3 Link Steam${id === "link-steam" ? "" : " (already claimed)"}`,
      source,
      render: () => (
        <LivePreview snaps={{ me }} playerId={me.player.id}>
          <AppShell>
            <div className="flex justify-center">
              <LinkSteamView player={me.player} />
            </div>
          </AppShell>
        </LivePreview>
      ),
    });
  }
  list.push(
    {
      id: "play-idle",
      group: signIn,
      title: "1.4 Play: not queued",
      source: "completed.me-player, completed.queue, ready_check.live",
      render: () => play(fixture.me("completed", "player"), fixture.queue("completed"), fixture.live("ready_check")),
    },
    {
      id: "play-place-held",
      group: signIn,
      title: "1.4 Play: place held",
      source: "derived from completed.me-player: a held place",
      render: () => play(placeHeldMe(), fixture.queue("voided_ready_check"), fixture.live("in_progress")),
    },
    {
      id: "play-in-queue",
      group: signIn,
      title: "1.5 Play: in queue",
      source: "ready_check.me-spectator, ready_check.queue, ready_check.live",
      render: () => play(fixture.me("ready_check", "spectator"), fixture.queue("ready_check"), fixture.live("ready_check")),
    },
    {
      id: "play-in-match",
      group: signIn,
      title: "1.4 Play: in a live match",
      source: "player_draft.me-player, player_draft.queue, player_draft.live",
      render: () => play(inMatchMe(), fixture.queue("player_draft"), fixture.live("player_draft")),
    },
    {
      id: "play-your-scrim",
      group: signIn,
      title: "1.4 Play: a scrim you captain",
      source: "scrim_champion_draft.me-captain, scrim_champion_draft.queue, scrim_champion_draft.live",
      render: () =>
        play(
          fixture.me("scrim_champion_draft", "captain"),
          fixture.queue("scrim_champion_draft"),
          fixture.live("scrim_champion_draft"),
        ),
    },
    {
      id: "play-cooldown",
      group: signIn,
      title: "1.6 Can't queue",
      source: "voided_ready_check.me-spectator, voided_ready_check.queue",
      render: () =>
        play(
          fixture.me("voided_ready_check", "spectator"),
          fixture.queue("voided_ready_check"),
          fixture.live("voided_ready_check"),
        ),
    },
  );

  const matchGroup = "2 Match: ready check";
  const me = fixture.me("ready_check", "player");
  const waiting = notReady(fixture.match("ready_check", "player"), me.player.id);
  list.push(
    {
      id: "ready-check-not-ready",
      group: matchGroup,
      title: "2.1 Ready check (you haven't readied)",
      source: "derived from ready_check.player: the viewer not ready",
      render: () => matchPage(waiting, me),
    },
    {
      id: "ready-up",
      group: matchGroup,
      title: "2.2 Ready Up (pop-up)",
      source: "derived from ready_check.player: the viewer not ready",
      render: () => (
        <LivePreview snaps={{ me, queue: fixture.queue("ready_check"), live: fixture.live("ready_check") }} playerId={me.player.id}>
          <AppShell>
            <PlayView me={me} queue={fixture.queue("ready_check")} live={fixture.live("ready_check")} />
          </AppShell>
          <ReadyUpView
            match={waiting}
            me={waiting.players.find((p) => p.id === me.player.id)!}
            isOpen
            onClose={() => {}}
          />
        </LivePreview>
      ),
    },
    {
      id: "need-sub",
      group: matchGroup,
      title: "2.3 Ready check: need a sub",
      source: "derived from ready_check.player: P9 missed it, the seat is offered to P13",
      render: () => matchPage(needSubMatch(), me),
    },
  );

  list.push(...draftEntries());
  list.push(...resultEntries());
  list.push(...subEntries());
  list.push(...statsEntries());

  list.push({
    id: "components",
    group: "Components",
    title: "TurnBanner, TurnStrip, TeamPanel, HeroGrid, ChoiceCard, StatTile, DataTable, …",
    source: "champion_draft.captain, coinflip.captain, completed.player",
    render: () => <ComponentSheet />,
  });

  for (const scenario of SCENARIOS) {
    for (const view of VIEWS) {
      if (!has(`${scenario}.${view}`) || !has(`${scenario}.me-${view}`)) continue;
      list.push(matchEntry(scenario, view));
    }
  }
  return list;
}

/** M6: the draft, the lobby and the game, plus the scrim screens. */
function draftEntries(): Entry[] {
  const group = "2 Match: draft and game";
  const scrims = "5 Scrims";
  const from = (scenario: string, view: View) => ({
    source: `${scenario}.${view}, ${scenario}.me-${view}`,
    render: () => matchPage(fixture.match(scenario, view), fixture.me(scenario, view)),
  });
  return [
    { id: "captain-vote", group, title: "2.4 Captain vote", ...from("captain_phase", "player") },
    {
      id: "captain-vote-ineligible",
      group,
      title: "2.4 Captain vote (some can't captain)",
      source: "derived from captain_phase.player: P5 and P6 not eligible, 5 matches needed",
      render: () => matchPage(ineligibleVoteMatch(), fixture.me("captain_phase", "player")),
    },
    { id: "captain-vote-watching", group, title: "2.4 Captain vote (watching)", ...from("captain_phase", "spectator") },
    {
      id: "captain-vote-auto",
      group,
      title: "2.4 Captain vote (Auto Captain on)",
      source: "derived from captain_phase.me-player: auto_captain on",
      render: () => matchPage(fixture.match("captain_phase", "player"), autoCaptainMe()),
    },
    { id: "player-draft-pick", group, title: "2.5 Player draft: your pick", ...from("player_draft", "captain") },
    { id: "player-draft-waiting", group, title: "2.5 Player draft: waiting", ...from("player_draft", "player") },
    { id: "coinflip-choose", group, title: "2.6 Coinflip: you won", ...from("coinflip", "captain") },
    { id: "coinflip-waiting", group, title: "2.6 Coinflip: waiting", ...from("coinflip", "player") },
    { id: "hero-draft-turn", group, title: "2.7 Hero draft: your turn", ...from("champion_draft", "captain") },
    {
      id: "hero-draft-waiting",
      group,
      title: "2.8 Hero draft: other captain's turn",
      source: "derived from champion_draft.captain: seen by P2, the other captain",
      render: () => {
        const { match, me } = waitingDraft();
        return matchPage(match, me);
      },
    },
    { id: "hero-draft-watching", group, title: "2.9 Hero draft: watching", ...from("champion_draft", "spectator") },
    { id: "lobby-code-host", group, title: "2.10 Enter lobby code (host)", ...from("lobby_code", "captain") },
    { id: "lobby-code-waiting", group, title: "2.10 Lobby code: waiting for the host", ...from("lobby_code", "player") },
    {
      id: "lobby",
      group,
      title: "2.11 Lobby (bot-hosted, captain)",
      source: "derived from in_progress.captain: an API lobby not started yet",
      render: () => matchPage(apiLobbyMatch("captain"), fixture.me("in_progress", "captain")),
    },
    {
      id: "lobby-watching",
      group,
      title: "2.11 Lobby (watching)",
      source: "derived from in_progress.spectator: an API lobby not started yet",
      render: () => matchPage(apiLobbyMatch("spectator"), fixture.me("in_progress", "spectator")),
    },
    { id: "in-game", group, title: "3.1 In game", ...from("in_progress", "player") },
    { id: "scrim-claim", group: scrims, title: "5.6 Scrim: claim captain", ...from("scrim_captain_claim", "spectator") },
    { id: "scrim-coinflip", group: scrims, title: "5.7 Scrim: coinflip", ...from("scrim_coinflip", "captain") },
    { id: "scrim-ready", group: scrims, title: "5.7 Scrim: ready to draft", ...from("scrim_ready_to_draft", "captain") },
    { id: "scrim-draft", group: scrims, title: "Scrim hero draft", ...from("scrim_champion_draft", "captain") },
    { id: "scrim-drafted", group: scrims, title: "Scrim drafted", ...from("scrim_drafted", "captain") },
  ];
}

/** M7: reporting, confirming and the finished match. */
function resultEntries(): Entry[] {
  const group = "3 Game and result";
  const from = (scenario: string, view: View) => ({
    source: `${scenario}.${view}, ${scenario}.me-${view}`,
    render: () => matchPage(fixture.match(scenario, view), fixture.me(scenario, view)),
  });
  const withDialog = (scenario: string, dialog: "report" | "dispute") => ({
    source: `${scenario}.captain, ${scenario}.me-captain, with the dialog open`,
    render: () => {
      const match = fixture.match(scenario, "captain");
      const me = fixture.me(scenario, "captain");
      const Dialog = dialog === "report" ? ReportDialog : DisputeDialog;
      return (
        <LivePreview snaps={{ me, [matchTopic(match.id)]: match }} playerId={me.player.id}>
          <MatchView match={match} />
          <Dialog match={match} isOpen onOpenChange={() => {}} />
        </LivePreview>
      );
    },
  });
  return [
    { id: "in-game-captain", group, title: "3.1 In game (captain)", ...from("in_progress", "captain") },
    { id: "report", group, title: "3.2 Report result (captain)", ...withDialog("in_progress", "report") },
    { id: "confirm", group, title: "3.3 Confirm result (other captain)", ...from("awaiting_confirmation", "captain") },
    { id: "confirm-waiting", group, title: "3.3 Waiting for the other captain", ...from("awaiting_confirmation", "player") },
    { id: "dispute-note", group, title: "3.4 Dispute note", ...withDialog("awaiting_confirmation", "dispute") },
    {
      id: "score-names",
      group,
      title: "3.5 Match scoreboard names (captain)",
      ...from("awaiting_confirmation_scoreboard", "captain"),
    },
    { id: "result", group, title: "3.6 Result (player)", ...from("completed", "player") },
    { id: "result-watching", group, title: "3.6 Result (watching)", ...from("completed", "spectator") },
    { id: "disputed", group, title: "3.7 Result disputed", ...from("disputed", "captain") },
    { id: "cancelled", group, title: "3.8 Match cancelled (back in queue)", ...from("voided_ready_check", "player") },
    {
      id: "cancelled-missed",
      group,
      title: "3.8 Match cancelled (missed the ready check)",
      ...from("voided_ready_check", "spectator"),
    },
  ];
}

/** M8: subs, early leaves and the toasts. */
function subEntries(): Entry[] {
  const group = "4 Subs, early leaves and notices";
  const from = (scenario: string, view: View) => ({
    source: `${scenario}.${view}, ${scenario}.me-${view}`,
    render: () => matchPage(fixture.match(scenario, view), fixture.me(scenario, view)),
  });
  const requesting = (scenario: string, view: View) => ({
    source: `${scenario}.${view}, with the dialog open; subs.options answered as the server would`,
    render: () => {
      const match = fixture.match(scenario, view);
      const me = fixture.me(scenario, view);
      const answer = (name: string) =>
        name === "subs.options"
          ? { ok: true, result: subOptions(match, me.player.id) }
          : { ok: false, error: "This is the screen gallery: nothing was sent." };
      return (
        <LivePreview snaps={{ me, [matchTopic(match.id)]: match }} playerId={me.player.id} answer={answer}>
          <MatchView match={match} />
          <SubRequestDialog match={match} isOpen onOpenChange={() => {}} />
        </LivePreview>
      );
    },
  });
  const offered = (scenario: string) => ({
    source: `${scenario}.me-spectator (its offer), on Play`,
    render: () => {
      const me = fixture.me(scenario, "spectator");
      return (
        <LivePreview snaps={{ me, queue: fixture.queue(scenario), live: fixture.live(scenario) }} playerId={me.player.id}>
          <AppShell>
            <PlayView me={me} queue={fixture.queue(scenario)} live={fixture.live(scenario)} />
          </AppShell>
          <OfferDialog />
        </LivePreview>
      );
    },
  });
  return [
    { id: "sub-request", group, title: "4.1 Request a sub (player)", ...requesting("player_draft", "player") },
    { id: "sub-request-captain", group, title: "4.1 Request a sub (captain)", ...requesting("in_progress", "captain") },
    {
      id: "sub-name",
      group,
      title: "4.2 Name a sub",
      source: "player_draft_sub_naming.captain, with the dialog open (search needs the dev server)",
      render: () => {
        const match = fixture.match("player_draft_sub_naming", "captain");
        const me = fixture.me("player_draft_sub_naming", "captain");
        return (
          <LivePreview snaps={{ me, [matchTopic(match.id)]: match }} playerId={me.player.id}>
            <MatchView match={match} />
            <SubNameDialog match={match} requestId={match.subs[0]?.id ?? null} onClose={() => {}} />
          </LivePreview>
        );
      },
    },
    { id: "sub-naming-notice", group, title: "4.2 Naming a sub (the notice)", ...from("player_draft_sub_naming", "captain") },
    { id: "sub-approve", group, title: "4.3 Approve sub out (other captain)", ...from("player_draft_sub_approval", "captain") },
    { id: "sub-approval-waiting", group, title: "4.3 Waiting for approval", ...from("player_draft_sub_approval", "player") },
    { id: "sub-invite", group, title: "4.4 Sub invite", ...offered("player_draft_sub_open") },
    { id: "spot-offer", group, title: "4.5 Spot offered", ...offered("in_progress_sub_offered") },
    { id: "paused", group, title: "4.6 Match paused for a sub (watching)", ...from("player_draft_sub_open", "spectator") },
    { id: "paused-leaving", group, title: "4.6 Paused: you're the one leaving", ...from("in_progress_sub_offered", "player") },
    {
      id: "early-leave",
      group,
      title: "4.7 Report an early leave (captain)",
      source: "in_progress.captain, with the dialog open",
      render: () => {
        const match = fixture.match("in_progress", "captain");
        const me = fixture.me("in_progress", "captain");
        return (
          <LivePreview snaps={{ me, [matchTopic(match.id)]: match }} playerId={me.player.id}>
            <MatchView match={match} />
            <EarlyLeaveDialog match={match} isOpen onOpenChange={() => {}} />
          </LivePreview>
        );
      },
    },
    { id: "early-leave-answer", group, title: "4.8 Answer an early leave (other captain)", ...from("in_progress_early_leave", "captain") },
    { id: "early-leave-waiting", group, title: "4.8 Early leave waiting (player)", ...from("in_progress_early_leave", "player") },
    { id: "refill", group, title: "2.3 Ready check refill: one joined", ...from("ready_check_refill", "player") },
    {
      id: "toasts",
      group,
      title: "4.9 Toasts",
      source: "no data: raises each toast the app derives from snapshots",
      render: () => <ToastSheet />,
    },
  ];
}

/** M9: matches, a past match, the leaderboard, profiles and the random draft. */
function statsEntries(): Entry[] {
  const group = "5 Matches, stats and tools";
  const matches = (filter: MatchFilter) => {
    const live = fixture.live("in_progress").matches;
    const rows = listed(live, matchList().matches, null, filter);
    return page(
      <MatchesView
        filter={filter}
        onFilter={() => {}}
        rows={rows}
        loadingRecent={false}
        failed={false}
        onRetry={() => {}}
        hasMore={filter !== "live"}
        loadingMore={false}
        onLoadMore={() => {}}
      />,
    );
  };
  const me = fixture.me("completed", "player");
  const linkedMe = { ...me.player, steam: { linked: true, proven: true, verified: true, name: "P3Plays" } };
  const other = () => ({ ...seasonProfile(true), is_you: false, player: { id: "5", name: "P5", avatar_url: null } });
  return [
    {
      id: "matches",
      group,
      title: "5.1 Matches",
      source: "in_progress.live, then derived from completed.http-matches: three older rows and a next page",
      render: () => matches("all"),
    },
    { id: "matches-live", group, title: "5.1 Matches: live", source: "in_progress.live", render: () => matches("live") },
    {
      id: "match-detail",
      group,
      title: "5.2 Match",
      source: "derived from completed.http-match: awards, stat lines, ratings, length, an upset",
      render: () => (
        <LivePreview snaps={{ me }} playerId={me.player.id}>
          <PastMatchView detail={recordedMatch()} />
        </LivePreview>
      ),
    },
    {
      id: "match-detail-raw",
      group,
      title: "5.2 Match (as the fixture has it)",
      source: "completed.http-match",
      render: () => (
        <LivePreview snaps={{ me }} playerId={me.player.id}>
          <PastMatchView detail={http.match()} />
        </LivePreview>
      ),
    },
    {
      id: "leaderboard",
      group,
      title: "5.3 Leaderboard",
      source: "derived from completed.http-leaderboard: ten ranked players, P3 sixth",
      render: () => page(<LeaderboardView board={seasonLeaderboard()} />),
    },
    {
      id: "leaderboard-pinned",
      group,
      title: "5.3 Leaderboard (you're not ranked yet)",
      source: "derived from completed.http-leaderboard: P3 short of the minimum, pinned at the foot",
      render: () => page(<LeaderboardView board={seasonLeaderboard(true)} />),
    },
    {
      id: "leaderboard-empty",
      group,
      title: "5.3 Leaderboard (start of the season)",
      source: "completed.http-leaderboard",
      render: () => page(<LeaderboardView board={http.leaderboard()} />),
    },
    {
      id: "profile",
      group,
      title: "5.4 Profile (yours)",
      source: "derived from completed.http-profile and completed.me-player: placed, Steam linked",
      render: () => page(<ProfileView profile={seasonProfile()} me={linkedMe} />),
    },
    {
      id: "profile-other",
      group,
      title: "5.4 Profile (someone else's, in placement)",
      source: "derived from completed.http-profile",
      render: () => page(<ProfileView profile={other()} me={null} />),
    },
    {
      id: "profile-new",
      group,
      title: "5.4 Profile (one match in, Steam not linked)",
      source: "completed.http-profile, completed.me-player",
      render: () => page(<ProfileView profile={http.profile()} me={me.player} />),
    },
    {
      id: "random-draft",
      group,
      title: "5.5 Random draft",
      source: "completed.http-random-draft",
      render: () => page(<RandomDraftView draft={http.randomDraft()} rolling={false} onRoll={() => {}} />),
    },
    {
      id: "random-draft-empty",
      group,
      title: "5.5 Random draft (before a roll)",
      source: "no data",
      render: () => page(<RandomDraftView draft={null} rolling={false} onRoll={() => {}} />),
    },
  ];
}

/** Every toast 4.9 lists, raised once on open. */
function ToastSheet() {
  const fired = useRef(false);
  useEffect(() => {
    // Once, though development mode runs effects twice.
    if (fired.current) return;
    fired.current = true;
    notify.success("Teams picked", "You're on P2's Team");
    notify.success("You're in", "Match 1 · P2's Team", { label: "Open", onPress: () => {} });
    notify.success("Strike removed", "1 left");
    notify.success("Sub found", "P13 is in for P3");
    notify.warning("Offer expired", "Match 1");
    notify.error(new Error("That hero was just taken"));
  }, []);
  const me = fixture.me("completed", "player");
  return (
    <LivePreview snaps={{ me }} playerId={me.player.id}>
      <AppShell>
        <p className="text-sm text-muted">Toasts show at the bottom right (full width on phones).</p>
      </AppShell>
    </LivePreview>
  );
}

function matchEntry(scenario: string, view: View): Entry {
  const match = fixture.match(scenario, view);
  return {
    id: `${scenario}.${view}`,
    group: "Every fixture, by status",
    title: `${scenario} · ${view} (${match.status})`,
    source: `${scenario}.${view}, ${scenario}.me-${view}`,
    render: () => matchPage(fixture.match(scenario, view), fixture.me(scenario, view)),
  };
}

const ENTRIES = entries();

function Index() {
  const groups = [...new Set(ENTRIES.map((e) => e.group))];
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 px-4 py-8 sm:px-8">
      <div className="flex flex-col gap-2">
        <h1 className="text-3xl font-bold">Screens</h1>
        <p className="text-sm text-muted">
          Development only. Each screen runs on fixtures from <code>frontend/src/fixtures</code>, with the clock
          set to the fixtures&apos; time. Actions are refused.
        </p>
      </div>
      {groups.map((group) => (
        <section key={group} aria-labelledby={`g-${group}`} className="flex flex-col gap-3">
          <h2 id={`g-${group}`} className="text-lg font-bold">
            {group}
          </h2>
          <ul className="grid gap-2 sm:grid-cols-2">
            {ENTRIES.filter((e) => e.group === group).map((entry) => (
              <li key={entry.id}>
                <Link to={entry.id} className="block rounded-2xl outline-none focus-visible:ring-2 focus-visible:ring-focus">
                  <Card className="gap-1 border border-border px-4 py-3 hover:bg-surface-hover">
                    <span className="font-semibold">{entry.title}</span>
                    <span className="text-xs text-muted">{entry.source}</span>
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}

function Detail() {
  const { entry: id } = useParams();
  const entry = ENTRIES.find((e) => e.id === id);
  if (!entry) return <Index />;
  return (
    // Keyed by entry, so moving between entries starts a fresh FakeServer.
    <Fragment key={entry.id}>
      {entry.render()}
      <div className="fixed bottom-4 left-4 z-50 flex items-center gap-2">
        <ButtonLink to="/dev/screens/legacy" variant="secondary" size="sm">
          Screens
        </ButtonLink>
        <Chip size="sm" variant="soft">
          {entry.title}
        </Chip>
      </div>
    </Fragment>
  );
}

export default function ScreenGallery() {
  return (
    <Routes>
      <Route index element={<Index />} />
      <Route path=":entry" element={<Detail />} />
    </Routes>
  );
}
