// /signin (A01, A02): Discord and Steam, the dev login when the server allows it, and every
// refusal in plain words.
import type { ReactNode } from "react";
import { Navigate, useSearchParams } from "react-router";

import { signInUrl, useSession } from "../../api/session";
import { ButtonLink } from "../../components/Button";
import { Icon } from "../../components/Icon";
import { Panel } from "../../components/Layout";
import { AppShell } from "../../components/shell/AppShell";
import { EmptyState, Skeleton } from "../../components/States";
import { Sticker } from "../../components/Sticker";
import { AdvertCard, Headline, Tagline, useLanding } from "./Landing";
import type { Landing } from "../../api/types";
import { useIsPhone } from "../../lib/useMediaQuery";
import type { Refusal } from "./refusals";
import { refusalFor, safeNext } from "./refusals";

const DEFAULT_HEADLINE = ["Twelve in.", "Two captains."] as const;
const DEFAULT_LEAD = "The league's Deadlock 6v6 inhouse. Queue here or in Discord: it's the same queue, the same draft and the same ladder.";

const HOW = [
  { title: "Queue", line: "Join with one press. When 12 are in, everyone gets Ready Up." },
  { title: "Draft", line: "Two captains pick players, then ban and pick heroes." },
  { title: "Play", line: "Lobby code, the game, then the result and your postgame." },
] as const;

function Disclosure({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="group border-t border-line first:border-t-0">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 py-1 text-body font-bold">
        {title}
        <Icon name="next" size={18} className="shrink-0 transition-state group-open:rotate-90" />
      </summary>
      <p className="pb-3 text-label text-muted">{children}</p>
    </details>
  );
}

/** The page's own hero, when staff have set no call to action. */
function DefaultHero({ withHow }: { withHow: boolean }) {
  return (
    <section aria-labelledby="hero-heading" className="flex min-w-0 flex-999 basis-160 flex-col gap-6">
      <Sticker tone="brand" className="self-start">
        League night, every night
      </Sticker>
      <h1 id="hero-heading" className="type-display text-poster max-md:text-board">
        {DEFAULT_HEADLINE[0]}
        <br />
        {DEFAULT_HEADLINE[1]}
      </h1>
      <p className="max-w-lead text-lead-lg text-muted">{DEFAULT_LEAD}</p>
      <span aria-hidden="true" className="flex gap-2">
        <span className="h-2 w-16 rounded-full bg-team-hk" />
        <span className="h-2 w-16 rounded-full bg-team-am" />
      </span>
      {withHow ? <HowItRuns /> : null}
    </section>
  );
}

function HowItRuns() {
  return (
    <ul aria-label="How it runs" className="grid w-full max-w-190 grid-cols-1 gap-3 sm:grid-cols-3">
      {HOW.map((item) => (
        <li key={item.title} className="flex flex-col gap-1 rounded-card border border-line p-4">
          <b className="text-body font-extrabold">{item.title}</b>
          <span className="text-label text-muted">{item.line}</span>
        </li>
      ))}
    </ul>
  );
}

/** The call to action staff set in the admin, in the whole of the hero's place: the tagline as
 * the headline and its lead, then the advert. An advert alone keeps the page's own words. */
function LandingHero({ landing, withAdvert }: { landing: Landing; withAdvert: boolean }) {
  const tagline = landing.headline_html !== null;
  return (
    <section aria-labelledby="hero-heading" className="flex min-w-0 flex-999 basis-160 flex-col gap-6">
      {landing.headline_html ? (
        <Headline id="hero-heading" html={landing.headline_html} />
      ) : (
        <h1 id="hero-heading" className="type-display text-poster max-md:text-board">
          {DEFAULT_HEADLINE[0]}
          <br />
          {DEFAULT_HEADLINE[1]}
        </h1>
      )}
      {landing.lead_html ? <Tagline html={landing.lead_html} /> : tagline ? null : <p className="max-w-lead text-lead-lg text-muted">{DEFAULT_LEAD}</p>}
      {withAdvert && landing.advert ? <AdvertCard advert={landing.advert} /> : null}
    </section>
  );
}

function SignInCard({ next, devLogin, invite }: { next: string; devLogin: boolean; invite: string | null }) {
  return (
    <Panel as="section" className="flex flex-col gap-4 p-9 max-md:p-6">
      <h2 className="text-title max-md:text-coin" id="signin-heading">
        Sign in
      </h2>
      <div className="flex flex-col gap-2">
        <ButtonLink to={signInUrl("discord", next)} external icon="discord" size="lg" fullWidth>
          Sign in with Discord
        </ButtonLink>
        <p className="text-caption text-muted">
          You need to be in the league&apos;s Discord server. We read your name, avatar and that you&apos;re a member, nothing else.
        </p>
      </div>
      <div className="flex flex-col gap-2">
        <ButtonLink to={signInUrl("steam", next)} external icon="steam" kind="ghost" size="lg" fullWidth>
          Sign in with Steam
        </ButtonLink>
        <p className="text-caption text-muted">
          Steam works once it&apos;s linked to your Discord account. Link it once from Me after you sign in with Discord.
        </p>
      </div>
      <div className="flex flex-col border-t border-line pt-2">
        <Disclosure title="Not in the server yet?">
          DayShift is for members of the league&apos;s Discord server.{" "}
          {invite ? (
            <>
              <a href={invite} className="font-bold text-foreground underline underline-offset-2">
                Join with the invite
              </a>
              , then sign in with Discord.
            </>
          ) : (
            "Ask whoever invited you for the server invite, then sign in with Discord."
          )}
        </Disclosure>
        <Disclosure title="Steam not linked yet?">
          Sign in with Discord, then open Me and press Link with Steam. After that, either button signs you in.
        </Disclosure>
      </div>
      {devLogin ? (
        <ButtonLink to={signInUrl("dev", next)} external kind="quiet" size="sm" className="self-start">
          Dev login (this server only)
        </ButtonLink>
      ) : null}
    </Panel>
  );
}

function RefusalCard({ refusal, next, invite }: { refusal: Refusal; next: string; invite: string | null }) {
  const discord = signInUrl("discord", refusal.action === "link" ? "/link-steam" : next);
  const main = (() => {
    switch (refusal.action) {
      case "invite":
        return invite ? (
          <ButtonLink to={invite} external icon="link" size="lg">
            Open the server invite
          </ButtonLink>
        ) : null;
      case "steam":
        return (
          <ButtonLink to={signInUrl("steam", next)} external icon="steam" size="lg">
            Try Steam again
          </ButtonLink>
        );
      case "link":
      case "discord":
        return (
          <ButtonLink to={discord} external icon="discord" size="lg">
            {refusal.action === "link" ? "Sign in with Discord" : "Try again"}
          </ButtonLink>
        );
    }
  })();
  return (
    <section aria-labelledby="refusal-heading" className="flex flex-col gap-4 rounded-panel border-2 border-line-strong bg-surface p-9 max-md:p-6">
      <span className="text-muted">
        <Icon name={refusal.eyebrow.includes("Steam") ? "steam" : "discord"} size={28} />
      </span>
      <span className="text-label font-bold text-muted">{refusal.eyebrow}</span>
      <h1 id="refusal-heading" className="text-board max-md:text-coin">
        {refusal.title}
      </h1>
      <p className="max-w-lead text-lead text-muted">{refusal.body}</p>
      <div className="flex flex-wrap items-center gap-3">
        {main}
        {refusal.action === "invite" ? (
          <ButtonLink to={discord} external kind="ghost" size="lg">
            Try again
          </ButtonLink>
        ) : null}
        <ButtonLink to="/signin" kind="quiet">
          Back to sign in
        </ButtonLink>
      </div>
      {refusal.note ? <p className="text-label text-muted">{refusal.note}</p> : null}
    </section>
  );
}

export function SignInPage() {
  const [params] = useSearchParams();
  const session = useSession();
  const landing = useLanding();
  const phone = useIsPhone();
  const next = safeNext(params.get("next"));
  const refusal = refusalFor(params.get("error"));
  const expired = params.get("expired") === "1";

  if (session.data?.signed_in && !refusal) return <Navigate to={next} replace />;

  const devLogin = session.data?.dev_login ?? false;
  const invite = session.data?.invite_url ?? null;
  return (
    <AppShell me={null}>
      {session.isPending ? (
        <Skeleton label="Loading sign-in" lines={3} />
      ) : expired && !refusal ? (
        <div className="flex flex-wrap items-start gap-6">
          <div className="min-w-0 flex-999 basis-140">
            <EmptyState
              headingLevel={1}
              art={
                <span className="text-muted">
                  <Icon name="user" size={36} />
                </span>
              }
              title="You've been signed out"
              action={
                <ButtonLink to={signInUrl("discord", next)} external icon="discord">
                  Sign in again
                </ButtonLink>
              }
            >
              Your session ran out, or you signed out in another tab. Sign in again and you&apos;ll come straight back to this page.
            </EmptyState>
          </div>
          <div className="min-w-0 flex-1 basis-90">
            <SignInCard next={next} devLogin={devLogin} invite={invite} />
          </div>
        </div>
      ) : refusal ? (
        <div className="flex flex-wrap items-start gap-6">
          <div className="flex min-w-0 flex-999 basis-140 flex-col">
            <RefusalCard refusal={refusal} next={next} invite={invite} />
          </div>
          <div className="min-w-0 flex-1 basis-90">
            <SignInCard next={next} devLogin={devLogin} invite={invite} />
          </div>
          <p className="basis-full text-label text-muted">Refusals say what happened and what to do, in plain words.</p>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-x-14 gap-y-10">
          {landing && (landing.headline_html || landing.advert) ? (
            <LandingHero landing={landing} withAdvert={!phone} />
          ) : (
            <DefaultHero withHow={!phone} />
          )}
          <div className="min-w-0 flex-1 basis-100">
            <SignInCard next={next} devLogin={devLogin} invite={invite} />
          </div>
          {/* On a phone the advert, or how it runs, comes after the sign-in card, so signing in is
              never a long scroll away. */}
          {phone && landing?.advert ? <AdvertCard advert={landing.advert} /> : null}
          {phone && !(landing && (landing.headline_html || landing.advert)) ? <HowItRuns /> : null}
        </div>
      )}
    </AppShell>
  );
}

export default SignInPage;
