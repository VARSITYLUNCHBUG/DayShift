// /matches/:id/{summary,timeline,replay,advanced} (R07 to R11, E02, M09): a finished match's
// record and postgame. Its twelve players see it in the room shell with their own night; everyone
// else sees the same record and depth in the app shell (P06, P07). Each tab is one deliberate
// click deeper, and the three deep ones load on their own.
import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { useParams } from "react-router";

import { queries, isNotFound } from "../../api/queries";
import { useSessionPlayer } from "../../api/session";
import type { MatchDetail, PostgameBody } from "../../api/types";
import { LiveStatus } from "../../app/LiveStatus";
import { Button, ButtonLink } from "../../components/Button";
import { PageTabs } from "../../components/Navigation";
import { AppShell } from "../../components/shell/AppShell";
import { RANKED_PHASES, SCRIM_PHASES } from "../../components/shell/RoomHeader";
import { RoomShell } from "../../components/shell/RoomShell";
import { EmptyState, ErrorState, Skeleton } from "../../components/States";
import { gameClock, matchNo } from "../shared/format";
import { BackLink } from "../shared/parts";
import NotFoundPage from "../NotFound";
import { Summary } from "./Summary";

const Timeline = lazy(() => import("./Timeline"));
const Replay = lazy(() => import("./Replay"));
const Advanced = lazy(() => import("./Advanced"));

export type PostgameTab = "summary" | "timeline" | "replay" | "advanced";
const TABS: readonly PostgameTab[] = ["summary", "timeline", "replay", "advanced"];

export const TAB_LABEL: Record<PostgameTab, string> = {
  summary: "Summary",
  timeline: "Timeline",
  replay: "Replay",
  advanced: "Advanced",
};

export function isTab(value: string | undefined): value is PostgameTab {
  return TABS.includes(value as PostgameTab);
}

/** Whether the viewer is one of the match's players. */
export function playedIn(detail: MatchDetail, playerId: string | undefined): boolean {
  return playerId !== undefined && detail.teams.some((team) => team.players.some((p) => p.id === playerId));
}

/** "Deadlock match 41207733 · 31:12 · stats from deadlock-api". */
function metaLine(detail: MatchDetail, body: PostgameBody | undefined): string {
  const doc = body?.status === "ready" ? body.data : null;
  const length = doc?.duration_s ?? detail.duration_s;
  return [
    detail.draft_name,
    detail.deadlock_match_id ? `Deadlock match ${detail.deadlock_match_id}` : null,
    length ? gameClock(length) : null,
    doc ? "stats from deadlock-api" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function Tabs({ id, meta }: { id: string; meta: string }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
      <PageTabs
        label="Postgame"
        items={TABS.map((tab) => ({ label: TAB_LABEL[tab], to: `/matches/${id}/${tab}` }))}
      />
      <span className="text-caption font-semibold text-muted tabular-nums">{meta}</span>
    </div>
  );
}

function TabLoading() {
  return <Skeleton label="Loading the tab" lines={5} avatar={false} />;
}

/** Everything under the tabs. */
function TabBody({ tab, detail, body, played }: { tab: PostgameTab; detail: MatchDetail; body: PostgameBody; played: boolean }) {
  if (tab === "summary") return <Summary detail={detail} body={body} played={played} />;
  if (body.status === "pending") {
    return (
      <EmptyState
        title={`No ${TAB_LABEL[tab].toLowerCase()} for this match yet`}
        action={
          <ButtonLink to={`/matches/${detail.id}/summary`} kind="ghost">
            Back to the summary
          </ButtonLink>
        }
      >
        {tab === "timeline"
          ? "The timeline is drawn from deadlock-api's match data."
          : tab === "replay"
            ? "The replay needs deadlock-api's position data."
            : "Every number here comes from deadlock-api's match data."}{" "}
        The summary says why it isn&apos;t here.
      </EmptyState>
    );
  }
  const Page = tab === "timeline" ? Timeline : tab === "replay" ? Replay : Advanced;
  return (
    <Suspense fallback={<TabLoading />}>
      <Page detail={detail} doc={body.data} you={body.you} />
    </Suspense>
  );
}

export function PostgamePage() {
  const { id = "", tab: rawTab } = useParams();
  const tab: PostgameTab = isTab(rawTab) ? rawTab : "summary";
  const player = useSessionPlayer();
  const detail = useQuery(queries.match(id));
  const body = useQuery(queries.postgame(id));
  const me = player ? { name: player.name, avatar: player.avatar } : null;

  let content: ReactNode;
  if (!isTab(rawTab)) {
    content = <NotFoundPage />;
  } else if (detail.isPending || body.isPending) {
    content = <Skeleton label="Loading the match" lines={6} />;
  } else if (isNotFound(detail.error)) {
    content = (
      <EmptyState
        title="We can't find that match"
        action={
          <ButtonLink to="/matches" kind="ghost">
            Matches
          </ButtonLink>
        }
      >
        The link may be old, or that match number doesn&apos;t exist. Nothing is broken on your side.
      </EmptyState>
    );
  } else if (detail.isError || body.isError) {
    content = (
      <ErrorState
        title="We can't load this match right now"
        action={
          <Button
            kind="ghost"
            onPress={() => {
              void detail.refetch();
              void body.refetch();
            }}
          >
            Try again
          </Button>
        }
      >
        The result is safe; this page just didn&apos;t load. Try again in a moment.
      </ErrorState>
    );
  } else {
    const played = playedIn(detail.data, player?.id);
    const inner = (
      <>
        <Tabs id={id} meta={metaLine(detail.data, body.data)} />
        <h1 className="sr-only">
          {matchNo(id)}: {TAB_LABEL[tab]}
        </h1>
        <TabBody tab={tab} detail={detail.data} body={body.data} played={played} />
      </>
    );
    if (played) {
      const scrim = detail.data.kind === "scrim";
      const phases = scrim ? SCRIM_PHASES : RANKED_PHASES;
      return (
        <RoomShell
          number={matchNo(id)}
          title={detail.data.draft_name}
          phases={phases}
          current={phases.length - 1}
          phaseLine={detail.data.status === "voided" ? "Cancelled" : "Result"}
          me={me}
          back={{ to: "/matches", label: "Back to Matches" }}
        >
          {inner}
        </RoomShell>
      );
    }
    return (
      <AppShell me={me} status={<LiveStatus />}>
        <BackLink to="/matches">Matches</BackLink>
        {inner}
      </AppShell>
    );
  }
  return (
    <AppShell me={me} status={<LiveStatus />}>
      {content}
    </AppShell>
  );
}

export default PostgamePage;
