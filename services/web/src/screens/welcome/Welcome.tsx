// /welcome (E10): your first night. How the queue runs, and what Matches, Ladder and Me will show
// once you've played: each one's empty state, with the one thing to do next.
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { useLiveMatches, useQueue } from "../../api/live";
import { queries } from "../../api/queries";
import { ButtonLink } from "../../components/Button";
import { Icon } from "../../components/Icon";
import type { IconName } from "../../components/Icon";
import { PageHeader } from "../../components/Layout";
import { Sticker } from "../../components/Sticker";
import { matchNo } from "../shared/format";
import { Progress } from "../shared/parts";
import { moreToStart } from "../play/state";

function Card({ title, to, icon, art, heading, children, action }: { title: string; to: string; icon?: IconName; art?: ReactNode; heading: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section aria-labelledby={`${to}-welcome`} className="flex min-w-0 flex-1 basis-80 flex-col gap-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id={`${to}-welcome`} className="text-section">
          {title}
        </h2>
        <Link to={to} className="inline-flex min-h-11 items-center text-label font-extrabold text-muted underline underline-offset-2">
          Open {title}
        </Link>
      </div>
      <div className="flex flex-1 flex-col items-center gap-3 rounded-panel border border-dashed border-line-strong px-6 py-10 text-center">
        {art ?? (icon ? <span className="text-muted"><Icon name={icon} size={32} /></span> : null)}
        <b className="type-display text-card">{heading}</b>
        <span className="text-label text-muted">{children}</span>
        {action}
      </div>
    </section>
  );
}

export function WelcomePage() {
  const queue = useQueue().data;
  const live = useLiveMatches().data;
  const profile = useQuery(queries.me(null));
  const watch = live?.matches[0];
  const placement = profile.data?.placement;
  return (
    <>
      <PageHeader title="Your first night" lead="Nothing played yet? This is how Matches, Ladder and Me look until you have." />
      <section aria-label="The queue" className="flex flex-wrap items-center gap-x-9 gap-y-4 rounded-panel border border-line-strong bg-surface px-7 py-6">
        <span className="flex flex-col gap-1">
          <span className="text-label font-bold text-muted">The queue{queue ? ` · ${moreToStart(queue)}` : ""}</span>
          <b className="type-display text-poster tabular-nums">
            {queue?.count ?? 0}
            <span className="text-muted">/{queue?.size ?? 12}</span>
          </b>
        </span>
        <div className="flex min-w-0 flex-1 basis-90 flex-col gap-4">
          <p className="text-lead">
            Join, and once {queue?.size ?? 12} are in you&apos;re in the next match. Everyone gets Ready Up, the captains pick players, then heroes are
            drafted. You don&apos;t have to captain.
          </p>
          <div className="flex flex-wrap gap-2.5">
            <ButtonLink to="/" size="lg">
              Join the queue
            </ButtonLink>
            <ButtonLink to="/ladder" kind="ghost" size="lg">
              See the ladder
            </ButtonLink>
          </div>
        </div>
      </section>
      <div className="flex flex-wrap gap-6">
        <Card
          title="Matches"
          to="/matches"
          icon="play"
          heading="No matches of yours yet"
          action={
            watch ? (
              <ButtonLink to={`/matches/${watch.id}`} kind="ghost">
                Watch {matchNo(watch.id)}
              </ButtonLink>
            ) : null
          }
        >
          Your matches land here after your first one, each with its postgame. Live matches are always open to watch.
        </Card>
        <Card
          title="Ladder"
          to="/ladder"
          art={
            <Sticker tone="raised" tilt="slight">
              Unranked
            </Sticker>
          }
          heading="You're unranked"
        >
          You get a rating and a ladder place after your placement matches. Until then you play at the league&apos;s starting rating.
          {placement ? (
            <span className="mt-3 block text-left">
              <Progress value={placement.played} max={placement.total} label={`${placement.played} of ${placement.total} placement matches`} />
            </span>
          ) : null}
        </Card>
        <Card
          title="Me"
          to="/me"
          icon="user"
          heading="Nothing to show yet"
          action={
            <ButtonLink to="/link-steam" kind="ghost" icon="steam">
              Link Steam
            </ButtonLink>
          }
        >
          Your rating history, heroes and recent matches fill in as you play. No strikes, no cooldowns. Link Steam now so your first results find you.
        </Card>
      </div>
    </>
  );
}

export default WelcomePage;
