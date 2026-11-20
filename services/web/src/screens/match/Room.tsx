// The frame every match status sits in: the room shell, the scorebug with both teams, the rail
// (chat, then the screen's own panels), Need a sub, the notices that need an answer, and the
// reconnecting state. On phones the chat is a full-screen view behind an icon button.
import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import { FocusScope } from "react-aria/FocusScope";

import { useSessionPlayer } from "../../api/session";
import { Button, IconButton } from "../../components/Button";
import { Portrait } from "../../components/Portrait";
import { useConnectionTrouble } from "../../components/shell/ConnectionBanner";
import { roomPhase } from "../../components/shell/RoomHeader";
import { RoomShell } from "../../components/shell/RoomShell";
import { Scorebug, TurnBanner } from "../../components/Scorebug";
import { Badge } from "../../components/Sticker";
import type { TeamKey } from "../../components/team";
import { SIDE_NAME, TEAM_CLASS } from "../../components/team";
import { cn } from "../../lib/cn";
import { useIsPhone } from "../../lib/useMediaQuery";
import { usePlayerId } from "../../live/hooks";
import type { MatchSnap, Team } from "../../live/protocol.gen";
import { captainLine, heroActions, isApprover, leftRight, nameOf, teamKey } from "../../match/model";
import { Chat, chatScopeLine, chatTitle, useUnread } from "./Chat";
import { EarlyLeaveAnswerSheet } from "./EarlyLeave";
import { PausedBanners, SubApproveSheet, SubDialogs, useSubDialogs } from "./Subs";
import { SwapAnswerSheet } from "./TeamSheet";
import { WishesEditor } from "./Wishes";

/** What the room knows about whoever is looking, for every screen inside it. */
export interface RoomContext {
  myId: string | null;
  myName: string;
  /** The connection has been down a while: controls are inert and clocks go faint. */
  isOffline: boolean;
}

const Ctx = createContext<RoomContext>({ myId: null, myName: "You", isOffline: false });

export function useRoom(): RoomContext {
  return useContext(Ctx);
}

/** Who is looking: the socket's hello says, or the session before it has. For screens, which
 * sit above the Room they render. */
export function useMe(match: MatchSnap): { myId: string | null; myName: string } {
  const session = useSessionPlayer();
  const helloId = usePlayerId();
  const myId = helloId ?? session?.id ?? null;
  const myName = match.players.find((p) => p.id === myId)?.name ?? session?.name ?? "You";
  return { myId, myName };
}

export interface Now {
  /** Whose move: "Your pick", "Ready check". */
  title: ReactNode;
  /** "Pick 4 of 12 · then Vesper picks · runs out: a random hero". */
  line?: ReactNode;
  /** The acting team's colour; cream when it's nobody's turn. */
  tone?: TeamKey | null;
  /** The step's server deadline. */
  deadline?: string | null;
  /** The clock's 30 s and 10 s announcement ("to pick"); one clock per page speaks. */
  announce?: string;
  /** A small line over the clock: "Draft done", "In game". */
  eyebrow?: ReactNode;
  /** The one action, under the clock on desktop. */
  action?: ReactNode;
  /** Shown instead of a clock (an elapsed game time). */
  clock?: ReactNode;
}

interface Props {
  match: MatchSnap;
  now: Now;
  /** The team on the clock: "On the clock" under its name. */
  acting?: Team | null;
  /** A line over each team's name: "Won the flip", "Picks players first". */
  eyebrows?: Partial<Record<Team, string>>;
  /** Show each team's heroes under its name (from the hero draft on). */
  heroes?: boolean;
  /** The phone's sticky action. */
  footer?: ReactNode;
  /** Rail panels under the chat. */
  rail?: ReactNode;
  /** The phone top's phase line ("Heroes · your pick"). */
  phaseLine?: string;
  children: ReactNode;
}

export function Room({ match, now, acting = null, eyebrows = {}, heroes = false, footer, rail, phaseLine, children }: Props) {
  const phone = useIsPhone();
  const session = useSessionPlayer();
  const { myId, myName } = useMe(match);
  const trouble = useConnectionTrouble();
  const isOffline = trouble !== "ok";
  const subs = useSubDialogs(match);
  const [chatOpen, setChatOpen] = useState(false);
  const unread = useUnread(match.chat, phone ? chatOpen : true);
  const { phases, current } = roomPhase(match.status, match.kind);
  const [left, right] = leftRight(match);
  const tone = now.tone ?? null;

  const chatButton =
    phone && match.chat ? (
      <span className="relative inline-flex">
        <IconButton
          icon={match.chat.scope === "team" ? "teamchat" : "chat"}
          label={unread > 0 ? `${chatTitle(match.chat)}, ${unread} new` : chatTitle(match.chat)}
          onPress={() => setChatOpen(true)}
        />
        {unread > 0 ? (
          <span aria-hidden="true" className="absolute -top-1 -right-1">
            <Badge>{unread > 9 ? "9+" : unread}</Badge>
          </span>
        ) : null}
      </span>
    ) : null;

  const actions = (
    <>
      {match.viewer.can_request_sub ? (
        phone ? (
          <IconButton icon="sub" label="Need a sub" onPress={subs.request} isDisabled={isOffline} />
        ) : (
          <Button kind="ghost" size="sm" onPress={subs.request} isDisabled={isOffline}>
            Need a sub
          </Button>
        )
      ) : null}
      {chatButton}
    </>
  );

  const chat =
    match.chat && !phone ? <Chat match={match} chat={match.chat} myId={myId} myName={myName} isOffline={isOffline} /> : null;
  const railContent =
    chat || rail ? (
      <>
        {chat}
        {rail}
      </>
    ) : null;

  const me = session ? { name: session.name, avatar: session.avatar } : null;

  return (
    <Ctx value={{ myId, myName, isOffline }}>
      <RoomShell
        number={`No. ${match.id}`}
        title={match.mode_name}
        phases={phases}
        current={current}
        tone={tone}
        phaseLine={phaseLine}
        deadline={now.deadline}
        actions={actions}
        me={me}
        banner={<PausedBanners match={match} myId={myId} onName={subs.name} />}
        bug={
          <Scorebug
            left={<TeamSide match={match} team={left} acting={acting} eyebrow={eyebrows[left]} heroes={heroes} />}
            right={<TeamSide match={match} team={right} acting={acting} eyebrow={eyebrows[right]} heroes={heroes} align="end" />}
            deadline={now.clock ? null : now.deadline}
            tone={tone}
            title={
              <>
                {now.eyebrow ? <span className="mb-1 block text-label font-bold text-muted">{now.eyebrow}</span> : null}
                {now.clock ? <span className="mb-1.5 block font-display text-clock text-foreground">{now.clock}</span> : null}
                {now.title}
              </>
            }
            line={now.line}
            action={now.action ? <div inert={isOffline}>{now.action}</div> : undefined}
            announce={now.announce}
            isStale={isOffline}
          />
        }
        phoneBug={
          <TurnBanner
            deadline={now.clock ? null : now.deadline}
            tone={tone}
            title={now.title}
            line={
              now.clock ? (
                <>
                  {now.clock}
                  {now.line ? <> · {now.line}</> : null}
                </>
              ) : (
                now.line
              )
            }
            announce={now.announce}
            isStale={isOffline}
          />
        }
        rail={railContent}
        footer={
          footer ? (
            <div inert={isOffline} className="flex gap-2.5 *:flex-1">
              {footer}
            </div>
          ) : undefined
        }
      >
        <div inert={isOffline} className="flex min-w-0 flex-col gap-7">
          {children}
        </div>
      </RoomShell>
      <Notices match={match} myId={myId} />
      <SubDialogs match={match} state={subs} />
      {phone && chatOpen && match.chat ? (
        <PhoneChat match={match} myId={myId} myName={myName} isOffline={isOffline} onClose={() => setChatOpen(false)} />
      ) : null}
    </Ctx>
  );
}

/** One notice sheet at a time (P04 rung 2): a sub to approve, then a swap, then an early leave. */
function Notices({ match, myId }: { match: MatchSnap; myId: string | null }) {
  const approve = match.subs.find((line) => isApprover(match, line, myId));
  if (approve) return <SubApproveSheet match={match} line={approve} />;
  const swap = match.swap.pending;
  if (swap && match.viewer.is_captain && swap.requested_by_id !== myId) return <SwapAnswerSheet match={match} offer={swap} />;
  const claim = match.early_leave.pending;
  if (claim && match.viewer.is_captain && claim.by_id !== myId) return <EarlyLeaveAnswerSheet match={match} claim={claim} />;
  return null;
}

/** One side of the scorebug: the side (once set), the team's name in its colour, the captain,
 * and its heroes from the hero draft on. */
function TeamSide({
  match,
  team,
  acting,
  eyebrow,
  heroes,
  align = "start",
}: {
  match: MatchSnap;
  team: Team;
  acting: Team | null;
  eyebrow?: string;
  heroes: boolean;
  align?: "start" | "end";
}) {
  const key = teamKey(match, team);
  const tone = TEAM_CLASS[key];
  const side = match.sides[team];
  const top = [side ? SIDE_NAME[side] : null, eyebrow].filter(Boolean).join(" · ");
  const end = align === "end";
  return (
    <div
      className={cn(
        "flex min-w-0 flex-1 basis-55 flex-col gap-0.5",
        end ? "items-end text-right max-md:items-start max-md:text-left" : "items-start text-left",
      )}
    >
      {top ? <span className={cn("text-caption font-bold", tone.text)}>{top}</span> : null}
      <span className={cn("font-display text-team break-words", tone.text)}>{nameOf(match, team)}</span>
      <span className="text-label text-muted">{captainLine(match, team)}</span>
      {acting === team ? <span className={cn("text-caption font-extrabold", tone.text)}>On the clock</span> : null}
      {heroes ? <TeamHeroes match={match} team={team} align={align} /> : null}
    </div>
  );
}

function TeamHeroes({ match, team, align }: { match: MatchSnap; team: Team; align: "start" | "end" }) {
  const key = teamKey(match, team);
  const side = match.sides[team];
  const { bans, picks } = heroActions(match);
  const mine = picks.filter((p) => p.team === team);
  const banned = bans.filter((b) => b.team === team);
  const slots = side ? match.champion_steps.filter((s) => s.side === side && s.action === "pick").length : 0;
  const open = Math.max(0, slots - mine.length);
  return (
    <div className={cn("mt-2 flex flex-col gap-1.5", align === "end" ? "items-end max-md:items-start" : "items-start")}>
      <ul aria-label={`${nameOf(match, team)}'s heroes`} className="flex flex-wrap gap-1.5">
        {mine.map((pick) => (
          <li key={pick.champion.id} className="flex w-14 flex-col items-center gap-0.5">
            <Portrait hero={pick.champion.name} src={pick.champion.icon_url} team={key} size="lg" />
            <span className="w-full truncate text-center text-micro font-bold">
              {pick.champion.name}
              {pick.random ? <span className="sr-only"> (random)</span> : null}
            </span>
          </li>
        ))}
        {Array.from({ length: open }, (_, i) => (
          <li key={`open-${i}`} className="flex w-14 flex-col items-center gap-0.5">
            <span aria-hidden="true" className={cn("size-14 rounded-full border-2 border-dashed", TEAM_CLASS[key].line)} />
            <span className="text-micro text-faint">Open</span>
          </li>
        ))}
      </ul>
      {banned.length ? (
        <span className="text-caption text-muted">
          Banned <span className="line-through">{banned.map((b) => b.champion.name).join(", ")}</span>
        </span>
      ) : null}
    </div>
  );
}

/** The phone's chat view (M06, M17): full screen, back to the room, your wishes over a team chat. */
function PhoneChat({
  match,
  myId,
  myName,
  isOffline,
  onClose,
}: {
  match: MatchSnap;
  myId: string | null;
  myName: string;
  isOffline: boolean;
  onClose: () => void;
}) {
  const chat = match.chat;
  if (!chat) return null;
  return (
    <FocusScope contain restoreFocus autoFocus>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={chatTitle(chat)}
        onKeyDownCapture={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            onClose();
          }
        }}
        className="fixed inset-0 z-40 flex flex-col bg-background"
      >
        <div className="flex min-h-14 items-center gap-2 border-b border-line px-2">
          <IconButton icon="back" kind="quiet" label="Back to the match" onPress={onClose} />
          <b className="text-body font-extrabold">{chatTitle(chat)}</b>
          <span className="ml-auto pr-2 text-caption text-muted">{chatScopeLine(match, chat)}</span>
        </div>
        {chat.scope === "team" && (match.viewer.can_wish || match.wishes.length > 0) ? (
          <div className="border-b border-line px-4 py-3.5">
            <WishesEditor match={match} myId={myId} compact />
          </div>
        ) : null}
        <Chat match={match} chat={chat} myId={myId} myName={myName} isOffline={isOffline} fill />
      </div>
    </FocusScope>
  );
}

export function sideTone(match: MatchSnap, team: Team | null | undefined): TeamKey | null {
  return team ? teamKey(match, team) : null;
}
