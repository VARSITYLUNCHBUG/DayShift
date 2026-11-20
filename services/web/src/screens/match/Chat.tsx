// The match chat (contract-wishes-chat): the one chat the viewer can see now, lobby or team. Plain
// text only, your own line straight away, a refusal under the composer with the draft kept.
import { Input, Label, TextField } from "@heroui/react";
import { useId, useLayoutEffect, useRef, useState } from "react";
import type { SyntheticEvent } from "react";

import { Button } from "../../components/Button";
import { cn } from "../../lib/cn";
import { clockTime } from "../../lib/format";
import type { ChatLine, ChatView, MatchSnap, Team } from "../../live/protocol.gen";
import { errorText } from "../../components/toast";
import { TEAM_CLASS } from "../../components/team";
import { useMatchAction } from "../../match/live";
import { nameOf, playerKey } from "../../match/model";

export const MAX_CHAT = 500;

interface Pending {
  id: string;
  body: string;
}

interface Props {
  match: MatchSnap;
  chat: ChatView;
  myId: string | null;
  myName: string;
  /** The socket is down: the composer waits ("Chat is back when you are"). */
  isOffline?: boolean;
  /** Phone: fills its own view rather than sitting in a rail panel. */
  fill?: boolean;
  className?: string;
}

/** "Lobby chat" or "Team chat". */
export function chatTitle(chat: ChatView): string {
  return chat.scope === "lobby" ? "Lobby chat" : "Team chat";
}

/** Who can read it, always shown: "All 12 players. Closes when teams are set." */
export function chatScopeLine(match: MatchSnap, chat: ChatView): string {
  if (chat.scope === "lobby") return `All ${match.players.length} players. Closes when teams are set.`;
  const team = match.viewer.team;
  return team ? `${nameOf(match, team)} only.` : "Your team only.";
}

let localIds = 0;

export function Chat({ match, chat, myId, myName, isOffline = false, fill = false, className }: Props) {
  const titleId = useId();
  const errorId = useId();
  const act = useMatchAction();
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<Pending[]>([]);
  const [error, setError] = useState<string | null>(null);
  const list = useRef<HTMLOListElement>(null);
  const count = chat.messages.length + pending.length;

  // Keep the newest line in view as lines arrive.
  useLayoutEffect(() => {
    const element = list.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [count]);

  const send = (event?: SyntheticEvent) => {
    event?.preventDefault();
    const body = draft.trim();
    if (!body || isOffline || !chat.open) return;
    const line = { id: `local-${(localIds += 1)}`, body };
    setPending((current) => [...current, line]);
    setDraft("");
    setError(null);
    const drop = () => setPending((current) => current.filter((p) => p.id !== line.id));
    act.run("chat.send", { match_id: match.id, body }).then(drop, (reason: unknown) => {
      drop();
      setError(errorText(reason));
      // The draft comes back so nothing is lost; unless they've started typing another.
      setDraft((current) => (current ? current : body));
    });
  };

  const tooLong = draft.length > MAX_CHAT;
  const myTeam: Team | null = match.viewer.team;
  const placeholder = isOffline
    ? "Chat is back when you are"
    : chat.scope === "lobby"
      ? "Message the lobby"
      : "Message your team";

  return (
    <section
      aria-labelledby={fill ? undefined : titleId}
      aria-label={fill ? chatTitle(chat) : undefined}
      className={cn("flex min-h-0 flex-col", fill ? "flex-1" : "rounded-panel border border-line bg-surface", className)}
    >
      {fill ? null : (
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-line px-4.5 py-4">
          <h2 id={titleId} className="text-card">
            {chatTitle(chat)}
          </h2>
          <span className="text-caption font-semibold text-muted">{chatScopeLine(match, chat)}</span>
        </div>
      )}
      <ol
        ref={list}
        aria-label={`${chatTitle(chat)} messages`}
        aria-live="polite"
        aria-relevant="additions"
        tabIndex={0}
        className={cn(
          "flex flex-col gap-3 overflow-y-auto py-4 outline-none",
          fill ? "min-h-0 flex-1 px-4" : "max-h-96 min-h-40 px-4.5",
        )}
      >
        {count === 0 ? <li className="m-auto text-caption text-muted">No messages yet. Say hello.</li> : null}
        {chat.messages.map((line) => (
          <Line key={line.id} match={match} line={line} isYou={line.player_id === myId} />
        ))}
        {pending.map((line) => (
          <Line
            key={line.id}
            match={match}
            line={{ id: line.id, player_id: myId ?? "", name: myName, team: myTeam, body: line.body, at: "" }}
            isYou
            isPending
          />
        ))}
      </ol>
      {chat.open ? (
        <form onSubmit={send} className={cn("flex flex-col gap-2 border-t border-line py-3", fill ? "px-4 pb-safe" : "px-3")}>
          <div className="flex items-center gap-2">
            <TextField
              value={draft}
              onChange={(value) => {
                setDraft(value);
                if (error) setError(null);
              }}
              isDisabled={isOffline}
              isInvalid={tooLong}
              aria-describedby={error ? errorId : undefined}
              className="min-w-0 flex-1"
            >
              <Label className="sr-only">{placeholder}</Label>
              <Input placeholder={placeholder} autoComplete="off" className="h-11 w-full" />
            </TextField>
            <Button type="submit" kind="secondary" size="sm" isDisabled={isOffline || !draft.trim() || tooLong}>
              Send
            </Button>
          </div>
          {tooLong ? (
            <span className="text-caption font-semibold text-danger">
              {draft.length} of {MAX_CHAT} characters. Shorten it to send.
            </span>
          ) : null}
          {error ? (
            <span id={errorId} role="alert" className="text-caption font-semibold text-danger">
              {error}
            </span>
          ) : null}
        </form>
      ) : (
        <p className="border-t border-line px-4.5 py-3.5 text-caption font-semibold text-muted">
          {chat.closed_reason ?? "This chat is read-only now."}
        </p>
      )}
    </section>
  );
}

function Line({
  match,
  line,
  isYou,
  isPending = false,
}: {
  match: MatchSnap;
  line: ChatLine;
  isYou: boolean;
  isPending?: boolean;
}) {
  const tone = playerKey(match, line.team);
  return (
    <li className={cn("flex flex-col gap-0.5", isPending && "opacity-70")}>
      <span className="flex items-baseline gap-2">
        <b className={cn("text-caption font-extrabold", tone ? TEAM_CLASS[tone].text : "text-foreground")}>
          {line.name}
          {isYou ? <span className="sr-only"> (you)</span> : null}
        </b>
        {line.at ? (
          <time dateTime={line.at} className="text-micro text-faint">
            {clockTime(line.at)}
          </time>
        ) : (
          <span className="text-micro text-faint">Sending…</span>
        )}
      </span>
      {/* Plain text: React escapes it, and pre-wrap keeps the sender's line breaks. */}
      <span className="text-body break-words whitespace-pre-wrap">{line.body}</span>
    </li>
  );
}

/** How many lines have arrived since the chat was last looked at, for the phone's badge. */
export function useUnread(chat: ChatView | null, isOpen: boolean): number {
  const lastId = chat?.messages.at(-1)?.id ?? null;
  const [seen, setSeen] = useState<string | null>(lastId);
  const [scope, setScope] = useState(chat?.scope ?? null);
  // Adjusting state while rendering (React's documented pattern), not in an effect.
  if (scope !== (chat?.scope ?? null)) {
    // A new chat (lobby → team): start counting afresh.
    setScope(chat?.scope ?? null);
    setSeen(lastId);
  } else if (isOpen && seen !== lastId) {
    setSeen(lastId);
  }
  if (!chat || isOpen) return 0;
  const index = chat.messages.findIndex((m) => m.id === seen);
  return index === -1 && seen !== null ? chat.messages.length : chat.messages.length - 1 - index;
}
