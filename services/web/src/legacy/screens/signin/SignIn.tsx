import { Alert, Card, linkVariants, Spinner } from "@heroui/react";
import type { ReactNode } from "react";
import { Navigate, useSearchParams } from "react-router";

import { signInUrl, useSession } from "../../../api/session";
import { ButtonLink } from "../../components/ButtonLink";
import {  DiscordMark, SteamMark } from "../../components/icons";
import { Lockup } from "../../../components/Brand";
import type { RefusalAction } from "./refusals";
import { refusalFor } from "./refusals";

// Discord's own app, for when the server's invite isn't set (DISCORD_INVITE_URL).
export const DISCORD_APP = "https://discord.com/app";

/** Only paths on this site; anything else goes to Play. */
export function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.includes("\\")) return "/";
  return raw;
}

/** /signin and /signin?error=<code>. Signed-in players without an error go straight on. */
export function SignInPage() {
  const [params] = useSearchParams();
  const session = useSession();
  const error = params.get("error");
  const next = safeNext(params.get("next"));
  if (session.isPending) {
    return (
      <Centered>
        <Spinner aria-label="Loading" />
      </Centered>
    );
  }
  if (session.data?.signed_in && !error) return <Navigate to={next} replace />;
  return (
    <SignInView
      error={error}
      next={next}
      devLogin={session.data?.dev_login ?? false}
      inviteUrl={session.data?.invite_url ?? null}
    />
  );
}

interface ViewProps {
  error: string | null;
  next: string;
  devLogin: boolean;
  /** Where "Open Discord" goes: the server's invite, or Discord's app without one. */
  inviteUrl?: string | null;
}

export function SignInView({ error, next, devLogin, inviteUrl = null }: ViewProps) {
  return (
    <Centered>
      {error ? (
        <RefusedCard code={error} next={next} inviteUrl={inviteUrl} />
      ) : (
        <SignInCard next={next} devLogin={devLogin} />
      )}
    </Centered>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-8">
      {children}
    </main>
  );
}

function DiscordButton({ next }: { next: string }) {
  return (
    <ButtonLink
      to={signInUrl("discord", next)}
      external
      size="lg"
      fullWidth
      className="h-13 gap-2.5 bg-discord text-base font-semibold text-discord-foreground hover:bg-discord-hover"
    >
      <DiscordMark />
      Sign in with Discord
    </ButtonLink>
  );
}

function SignInCard({ next, devLogin }: { next: string; devLogin: boolean }) {
  return (
    <Card className="w-full max-w-100 gap-3.5 rounded-3xl border border-border px-8 py-9 shadow-overlay">
      <div className="mb-3.5 flex items-center gap-3">
        <h1 className="flex">
          <Lockup size={28} />
        </h1>
      </div>
      <DiscordButton next={next} />
      <ButtonLink
        to={signInUrl("steam", next)}
        external
        size="lg"
        fullWidth
        className="h-13 gap-2.5 border border-default bg-steam text-base font-semibold text-steam-foreground hover:bg-steam-hover"
      >
        <SteamMark />
        Sign in with Steam
      </ButtonLink>
      {devLogin ? (
        // A plain link: /auth/ is Django's, so the browser loads it (HeroUI's Link would route it).
        <a href={signInUrl("dev", next)} className={linkVariants().base({ className: "self-center text-sm" })}>
          Dev login
        </a>
      ) : null}
    </Card>
  );
}

function RefusedCard({ code, next, inviteUrl }: { code: string; next: string; inviteUrl: string | null }) {
  const refusal = refusalFor(code);
  const tryAgain = next === "/" ? "/signin" : `/signin?${new URLSearchParams({ next }).toString()}`;
  const action = (kind: RefusalAction) => {
    switch (kind) {
      case "open-discord":
        return (
          <ButtonLink key={kind} to={inviteUrl ?? DISCORD_APP} external className="bg-warning font-semibold text-warning-foreground">
            Open Discord
          </ButtonLink>
        );
      case "try-again":
        return (
          <ButtonLink
            key={kind}
            to={tryAgain}
            variant="outline"
            className={refusal.tone === "warning" ? "border-warning/40 font-semibold text-warning-soft-foreground" : "font-semibold"}
          >
            Try again
          </ButtonLink>
        );
      case "discord":
        return <DiscordButton key={kind} next={next} />;
    }
  };
  return (
    <Alert status={refusal.tone} className="w-full max-w-100 flex-col items-stretch gap-3 rounded-2xl p-4">
      <div className="flex items-center gap-2.5">
        <Alert.Indicator />
        <Alert.Content>
          <Alert.Title className="text-base font-semibold">{refusal.title}</Alert.Title>
        </Alert.Content>
      </div>
      <div className="flex flex-wrap gap-2">{refusal.actions.map(action)}</div>
    </Alert>
  );
}
