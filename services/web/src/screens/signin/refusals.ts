// What each sign-in refusal (league/web/auth/errors.py, `/signin?error=<code>`) says: what
// happened and the one thing to do, in plain words. Never the code itself.

export type RefusalCode =
  | "not-member"
  | "denied"
  | "discord-down"
  | "state"
  | "steam-unproven"
  | "steam-taken"
  | "steam-down"
  | "inactive"
  | "signed-out";

/** The next step a refusal offers, after its title and words. */
export type RefusalAction = "invite" | "discord" | "steam" | "link";

export interface Refusal {
  /** Above the title: which way in didn't work. */
  eyebrow: string;
  title: string;
  body: string;
  /** The main way on; the others follow as quieter links. */
  action: RefusalAction;
  /** Under the buttons. */
  note?: string;
}

const DISCORD = "Sign in with Discord didn't work";
const STEAM = "Sign in with Steam didn't work";

export const REFUSALS: Record<RefusalCode, Refusal> = {
  "not-member": {
    eyebrow: DISCORD,
    title: "You're not in the league's Discord server",
    body: "DayShift is for members of the server. Your Discord account isn't in it yet. Join with the invite, then try again: same account, nothing else to set up.",
    action: "invite",
    note: "The invite opens in Discord. Once you're in, Try again takes you straight to Play.",
  },
  denied: {
    eyebrow: "Sign-in cancelled",
    title: "You cancelled the sign-in",
    body: "Nothing was shared with DayShift. Whenever you're ready, sign in again: we only read your name, avatar and that you're in the server.",
    action: "discord",
  },
  "discord-down": {
    eyebrow: DISCORD,
    title: "Discord didn't answer",
    body: "Discord's sign-in is slow or down right now. Nothing is wrong on your side. Try again in a minute.",
    action: "discord",
  },
  state: {
    eyebrow: "The sign-in link ran out",
    title: "Start the sign-in again",
    body: "A sign-in link works once, for a few minutes, in the browser that started it. This one had already been used, ran out or came from another browser.",
    action: "discord",
  },
  "steam-unproven": {
    eyebrow: STEAM,
    title: "That Steam account isn't linked yet",
    body: "Steam sign-in only works for a Steam account that's linked to a Discord account. Sign in with Discord first, then link Steam from Me. After that, either button works.",
    action: "link",
    note: "Signing in this way takes you to Link Steam.",
  },
  "steam-taken": {
    eyebrow: STEAM,
    title: "Someone else proved that Steam account",
    body: "Another player signed in with this Steam account, which proves it's theirs, so it can't sign you in. Sign in with Discord instead. If it really is yours, ask staff in #support.",
    action: "discord",
  },
  "steam-down": {
    eyebrow: STEAM,
    title: "Steam didn't answer",
    body: "Steam's sign-in page is slow or down right now. Nothing is wrong on your side. Try again in a minute, or sign in with Discord.",
    action: "steam",
  },
  inactive: {
    eyebrow: "This account is switched off",
    title: "Staff have switched your account off",
    body: "While it's off, it can't sign in or queue. If you think that's a mistake, ask staff in the league's Discord.",
    action: "discord",
  },
  "signed-out": {
    eyebrow: "Linking Steam",
    title: "Sign in first, then link Steam",
    body: "Linking a Steam account needs you signed in with Discord, so we know whose it is. Sign in, then link Steam from Me.",
    action: "link",
  },
};

/** Any code the server sends that this page doesn't know yet. */
export const UNKNOWN_REFUSAL: Refusal = {
  eyebrow: "Sign-in didn't work",
  title: "Sign-in didn't work",
  body: "Something stopped the sign-in. Try again. If it keeps happening, ask staff in #support.",
  action: "discord",
};

export function refusalFor(code: string | null): Refusal | null {
  if (!code) return null;
  return code in REFUSALS ? REFUSALS[code as RefusalCode] : UNKNOWN_REFUSAL;
}

/** Where to go after signing in: a path on this site only, never another origin. */
export function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\") || raw.startsWith("/signin")) return "/";
  return raw;
}
