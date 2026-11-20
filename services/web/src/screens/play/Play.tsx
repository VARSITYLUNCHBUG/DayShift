// / (A04 to A07, M02, M15): the queue and your place in it, a place held for you, a cooldown with
// its strikes, your match or scrim, and tonight's live matches.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

import { useMe, usePageAction, useQueue } from "../../api/live";
import type { MeSnap, QueueSnap } from "../../api/live";
import { queries } from "../../api/queries";
import { Button, ButtonLink } from "../../components/Button";
import { Countdown } from "../../components/Countdown";
import { InlineAlert } from "../../components/InlineAlert";
import { Panel } from "../../components/Layout";
import { StickyFooter } from "../../components/shell/TopBar";
import { ErrorState, Skeleton } from "../../components/States";
import { StatusChip } from "../../components/Navigation";
import { errorText, notify } from "../../components/toast";
import { useServerNow } from "../../live/hooks";
import { cn } from "../../lib/cn";
import { clockTime, plural, shortDate, waitLength } from "../../lib/format";
import { useIsPhone } from "../../lib/useMediaQuery";
import { matchNo, ordinal, STATUS_LABEL } from "../shared/format";
import { Progress, QueueFill, Steps, StrikeDots } from "../shared/parts";
import { LastMatchPanel, TonightPanel, YouPanel } from "./Rail";
import { COOLDOWN_REASON, moreToStart, playState } from "./state";

const HOW_IT_RUNS = [
  { title: "Join the queue", line: "Your place goes by priority, not by who joined first. Only you see yours." },
  { title: "Ready Up at 12", line: "Everyone gets a Ready Up pop-up, here and in Discord, with a clock." },
  { title: "Captains and the draft", line: "Two captains pick players, then ban and pick heroes. Then the lobby code and the game." },
];

function nextSteps(queue: QueueSnap) {
  const left = Math.max(0, queue.size - queue.count);
  return [
    {
      title: left === 0 ? "The queue is full" : `${left} more to go`,
      line: "Keep this tab open, or don't: the pop-up also comes to you in Discord.",
    },
    {
      title: `Ready Up pops when it's ${queue.size}`,
      line: "You get a short clock to press Ready. Missing it is a strike and a short cooldown.",
    },
    { title: "Captains, then the player draft", line: `Lobby chat opens for all ${queue.size} while the captains pick.` },
  ];
}

/** The queue's count as the page's big number: "8/12". */
function BigCount({ count, size }: { count: number; size: number }) {
  return (
    <p className="type-display text-mega leading-none tracking-display tabular-nums max-md:text-poster" aria-label={`${count} of ${size} in the queue`}>
      {count}
      <span className="text-muted">/{size}</span>
    </p>
  );
}

function Join({ label = "Join the queue", disabled = false }: { label?: string; disabled?: boolean }) {
  const action = usePageAction();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-3">
      <Button
        size="lg"
        className="min-w-80 max-md:min-w-0"
        isDisabled={disabled}
        isPending={action.pending === "queue.join"}
        pendingLabel="Joining…"
        onPress={() => {
          setError(null);
          action.run("queue.join", {}).then(
            () => notify.info("You're in the queue"),
            (reason: unknown) => setError(errorText(reason)),
          );
        }}
      >
        {label}
      </Button>
      {error ? <InlineAlert title="You're not in the queue">{error}</InlineAlert> : null}
    </div>
  );
}

function Leave() {
  const action = usePageAction();
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-3">
      <Button
        kind="danger"
        size="lg"
        className="min-w-64 max-md:min-w-0"
        isPending={action.pending === "queue.leave"}
        pendingLabel="Leaving…"
        onPress={() => {
          setError(null);
          action.run("queue.leave", {}).then(
            () => notify.info("You left the queue", "Your place is held for a few minutes if you change your mind."),
            (reason: unknown) => setError(errorText(reason)),
          );
        }}
      >
        Leave queue
      </Button>
      {error ? <InlineAlert title="You're still in the queue">{error}</InlineAlert> : null}
    </div>
  );
}

/** A big clock beside its sentence and action (A06, A07). */
function ClockCard({ deadline, under, children, tone = "line" }: { deadline: string; under: string; children: ReactNode; tone?: "line" | "danger" }) {
  return (
    <section className={`flex flex-wrap items-center gap-x-9 gap-y-4 rounded-panel border-2 bg-surface px-7 py-6 max-md:px-5 ${tone === "danger" ? "border-danger" : "border-line-strong"}`}>
      <span className="flex flex-col gap-1">
        <Countdown deadline={deadline} size="scorebug" label={under} announce={under} />
        <span className="text-label font-semibold text-muted">{under}</span>
      </span>
      <div className="flex min-w-0 flex-1 basis-80 flex-col gap-4">{children}</div>
    </section>
  );
}

function YourMatch({ me }: { me: MeSnap }) {
  const cards = [me.match ? { label: "Your match", m: me.match } : null, me.scrim ? { label: "Your scrim", m: me.scrim } : null].filter(
    (card): card is { label: string; m: NonNullable<MeSnap["match"]> } => card !== null,
  );
  if (cards.length === 0) return null;
  return (
    <div className="flex flex-col gap-3">
      {cards.map(({ label, m }) => (
        <section
          key={m.id}
          aria-label={label}
          className="flex flex-wrap items-center justify-between gap-4 rounded-panel border-2 border-foreground bg-surface px-6 py-5"
        >
          <span className="flex flex-col gap-1">
            <span className="text-label font-bold text-muted">{label}</span>
            <b className="type-display text-section">
              {matchNo(m.id)} · {STATUS_LABEL[m.status]}
            </b>
            <span className="text-label text-muted">{m.is_captain ? "You're a captain." : m.team ? `You're on Team ${m.team}.` : "You're in this one."}</span>
          </span>
          <ButtonLink to={`/matches/${m.id}`} size="lg" icon="next">
            Open the room
          </ButtonLink>
        </section>
      ))}
    </div>
  );
}

function Strikes({ me }: { me: MeSnap }) {
  const profile = useQuery(queries.me(null));
  const cooldown = me.cooldown;
  const strikes = profile.data?.strikes;
  const count = strikes?.count ?? cooldown?.strikes ?? me.strikes;
  const per = strikes?.games_per_strike ?? 3;
  return (
    <Panel as="section" className="flex flex-1 basis-80 flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-section">{plural(count, "strike")}</h2>
        <StrikeDots count={count} />
      </div>
      <p className="text-label text-muted">
        {per} clean matches take one off.
        {strikes?.next_decay_at ? ` Or wait until ${shortDate(strikes.next_decay_at)} with no new strike.` : null}
      </p>
      {strikes && count > 0 ? <Progress value={strikes.progress} max={per} label={`${strikes.progress} of ${per} clean matches`} /> : null}
    </Panel>
  );
}

/** A07's "How long you wait": this kind of offence's ladder, with the rung that applied to you. */
function WaitLadder({ cooldown }: { cooldown: NonNullable<MeSnap["cooldown"]> }) {
  const { ladder, rung } = cooldown;
  if (rung === null || ladder.length < 2) return null;
  const last = ladder.length - 1;
  const reason = (COOLDOWN_REASON[cooldown.kind] ?? "this").toLowerCase();
  return (
    <Panel as="section" className="flex flex-1 basis-80 flex-col gap-3">
      <h2 className="text-section">How long you wait</h2>
      <p className="text-label text-muted">For a {reason}, by the strikes you already carry.</p>
      <ol className="flex flex-col">
        {ladder.map((minutes, index) => {
          const strikes = index === 0 ? "No strikes" : index === last ? `${plural(index, "strike")} or more` : plural(index, "strike");
          const you = index === rung;
          return (
            <li
              key={index}
              aria-current={you ? "true" : undefined}
              className={cn("flex justify-between gap-3 border-t border-line py-2 first:border-t-0", you ? "font-extrabold" : "text-muted")}
            >
              <span>{strikes}</span>
              <span className="tabular-nums">
                {waitLength(minutes)}
                {you ? " · you" : null}
              </span>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}

export function PlayPage() {
  const me = useMe();
  const queue = useQueue();
  const now = useServerNow();
  const phone = useIsPhone();

  if (!me.data || !queue.data) {
    if (me.state === "gone" || queue.state === "gone") {
      return (
        <ErrorState title="Play isn't set up yet" action={<ButtonLink to="/matches" kind="ghost">See the matches</ButtonLink>}>
          The bot hasn&apos;t opened a queue on this server yet. Ask staff in Discord.
        </ErrorState>
      );
    }
    return <Skeleton label="Loading the queue" lines={4} />;
  }

  const state = playState(me.data, queue.data, now);
  const q = queue.data;
  let main: ReactNode;
  let footer: ReactNode = null;

  switch (state.kind) {
    case "match":
      main = (
        <>
          <YourMatch me={me.data} />
          <p className="text-label text-muted">You can&apos;t queue while you&apos;re in a match. Once it&apos;s over, Play is right here.</p>
        </>
      );
      break;
    case "cooldown": {
      const cooldown = me.data.cooldown;
      main = (
        <>
          <header className="flex flex-col gap-3">
            <span className="text-label font-bold text-muted">{COOLDOWN_REASON[cooldown?.kind ?? "manual"] ?? "Cooldown"}</span>
            <h2 className="text-board max-md:text-coin">You can queue again at {clockTime(state.until)}</h2>
          </header>
          <ClockCard deadline={state.until} under="until you can queue">
            <p className="text-lead">{cooldown?.text}</p>
            <Button size="lg" isDisabled className="self-start">
              Join the queue
            </Button>
          </ClockCard>
          <div className="flex flex-wrap items-start gap-6">
            <Strikes me={me.data} />
            {cooldown ? <WaitLadder cooldown={cooldown} /> : null}
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <ButtonLink to="/me" kind="ghost">
              See your strikes on Me
            </ButtonLink>
            <span className="text-label text-muted">Think it&apos;s wrong? Ask staff in #support in Discord.</span>
          </div>
        </>
      );
      break;
    }
    case "held":
      main = (
        <>
          <header className="flex flex-col gap-3">
            <span className="text-label font-bold text-muted">You dropped out of the queue</span>
            <h2 className="text-board max-md:text-coin">Your place is held</h2>
          </header>
          <ClockCard deadline={state.until} under="left to rejoin">
            <p className="text-lead">
              You&apos;re still <b>{ordinal(state.position)}</b>. Rejoin before the clock runs out and you keep it. After that you go back in at your
              normal priority.
            </p>
            {phone ? null : <Join label={`Rejoin and keep ${ordinal(state.position)}`} />}
          </ClockCard>
          <QueueFill count={q.count} size={q.size} />
          <p className="text-label text-muted">
            {q.count} of {q.size} in the queue without you. Whether you pressed Leave or your connection dropped, we hold your place for a few
            minutes. Leaving before the pop is never a strike.
          </p>
        </>
      );
      footer = <Join label="Rejoin the queue" />;
      break;
    case "queued":
      main = (
        <>
          <header className="flex flex-wrap items-end justify-between gap-4">
            <div className="flex flex-col gap-2">
              <span className="text-lead font-bold text-muted">You&apos;re in the queue · your place</span>
              {state.position ? (
                <p className="flex items-baseline gap-4 type-display tracking-display tabular-nums">
                  <span className="text-mega leading-none max-md:text-poster">{ordinal(state.position)}</span>
                  {state.total ? <span className="text-board text-muted max-md:text-coin">of {state.total}</span> : null}
                </p>
              ) : (
                <p className="type-display text-poster">In</p>
              )}
            </div>
            <StatusChip live>
              {q.count}/{q.size} · {moreToStart(q)}
            </StatusChip>
          </header>
          <QueueFill count={q.count} size={q.size} />
          {phone ? null : <Leave />}
          <p className="text-body text-muted">
            Only you see your place. Places go by priority (recent leaves and strikes count), not by who joined first. If you leave or drop, your
            place is held for a few minutes.
          </p>
          <Panel as="section" className="flex flex-col gap-4">
            <h2 className="text-section">What happens next</h2>
            <Steps items={nextSteps(q)} />
          </Panel>
        </>
      );
      footer = <Leave />;
      break;
    case "closed":
      main = (
        <>
          <header className="flex flex-col gap-3">
            <span className="text-label font-bold text-muted">The queue</span>
            <h2 className="text-board max-md:text-coin">The queue is closed for now</h2>
          </header>
          <p className="max-w-lead text-lead text-muted">
            Staff have paused the queue, so nobody can join here or in Discord. Matches already running carry on. It opens again when they say so.
          </p>
        </>
      );
      break;
    case "idle":
      main = (
        <>
          <header className="flex flex-col gap-2">
            <span className="text-lead font-bold text-muted">The queue · {moreToStart(q)}</span>
            <BigCount count={q.count} size={q.size} />
          </header>
          <QueueFill count={q.count} size={q.size} />
          <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
            {phone ? null : <Join />}
            <span className="text-body text-muted">Leave any time before it fills. Same queue as /queue in Discord.</span>
          </div>
          <Panel as="section" className="flex flex-col gap-4">
            <h2 className="text-section">How it runs</h2>
            <Steps items={HOW_IT_RUNS} />
          </Panel>
        </>
      );
      footer = <Join />;
      break;
  }

  return (
    <div className="flex flex-wrap items-start gap-x-10 gap-y-8">
      <h1 className="sr-only">Play</h1>
      <div className="flex min-w-0 flex-999 basis-160 flex-col gap-6">
        {state.kind !== "match" ? <YourMatch me={me.data} /> : null}
        {main}
      </div>
      <aside aria-label="You and tonight" className="flex min-w-0 flex-1 basis-90 flex-col gap-4">
        <YouPanel />
        <TonightPanel />
        <LastMatchPanel />
      </aside>
      {phone && footer ? <StickyFooter>{footer}</StickyFooter> : null}
    </div>
  );
}

export default PlayPage;
