// What the sign-in page says for each refusal code in league/web/auth/errors.py.
// Django redirects to /signin?error=<code>; an unknown code gets the fallback.

export type RefusalCode =
  | "not-member"
  | "discord-denied"
  | "discord-failed"
  | "state"
  | "steam-denied"
  | "steam-invalid"
  | "steam-failed"
  | "steam-unproven"
  | "steam-taken"
  | "signed-out";

export type RefusalAction = "open-discord" | "try-again" | "discord";

export interface Refusal {
  title: string;
  /** warning: something the player must fix first. default: just try another way. */
  tone: "warning" | "default";
  actions: RefusalAction[];
}

export const REFUSALS: Record<RefusalCode, Refusal> = {
  "not-member": {
    title: "Join the Discord server first",
    tone: "warning",
    actions: ["open-discord", "try-again"],
  },
  "discord-denied": { title: "Discord sign-in was cancelled", tone: "default", actions: ["try-again"] },
  "discord-failed": { title: "Discord didn't answer. Try again", tone: "warning", actions: ["try-again"] },
  state: { title: "That sign-in link has expired", tone: "default", actions: ["try-again"] },
  "steam-denied": { title: "Steam sign-in was cancelled", tone: "default", actions: ["try-again"] },
  "steam-invalid": { title: "Steam's answer didn't check out", tone: "warning", actions: ["try-again"] },
  "steam-failed": { title: "Steam didn't answer. Try again", tone: "warning", actions: ["try-again"] },
  "steam-unproven": { title: "This Steam account isn't linked", tone: "default", actions: ["discord"] },
  "steam-taken": {
    title: "Another player has this Steam account",
    tone: "warning",
    actions: ["try-again"],
  },
  "signed-out": { title: "Sign in first", tone: "default", actions: ["discord"] },
};

export const UNKNOWN_REFUSAL: Refusal = {
  title: "Sign-in didn't work",
  tone: "warning",
  actions: ["try-again"],
};

export function refusalFor(code: string): Refusal {
  return code in REFUSALS ? REFUSALS[code as RefusalCode] : UNKNOWN_REFUSAL;
}
