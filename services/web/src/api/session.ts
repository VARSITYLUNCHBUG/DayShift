import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getJson, post } from "./http";

/** GET /api/session/ (league/web/auth/views.py `session_view`). */
export interface Session {
  signed_in: boolean;
  player: {
    id: string;
    name: string;
    avatar: string | null;
    /** Their own Steam links, oldest first. Never a Steam ID. */
    steam: { name: string; proven: boolean; verified: boolean }[];
  } | null;
  dev_login: boolean;
  /** The server's invite (DISCORD_INVITE_URL), when one is set. */
  invite_url: string | null;
  /** The Ko-fi page (KOFI_URL) the footer links to, when one is set. */
  kofi_url: string | null;
}

export const SESSION_KEY = ["session"] as const;

export function useSession() {
  return useQuery({
    queryKey: SESSION_KEY,
    queryFn: () => getJson<Session>("/api/session/"),
    staleTime: 60_000,
  });
}

/** The signed-in player as already loaded (SignedIn loads the session before any page renders),
 * without asking the server: for chrome such as the shells' "Me" link. */
export function useSessionPlayer(): Session["player"] {
  const { data } = useQuery({
    queryKey: SESSION_KEY,
    queryFn: () => getJson<Session>("/api/session/"),
    enabled: false,
  });
  return data?.player ?? null;
}

export function useSignOut() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => post("/auth/logout/"),
    onSettled: () => client.invalidateQueries({ queryKey: SESSION_KEY }),
  });
}

/** Where Django's sign-in starts; `next` brings the player back to where they were. */
export function signInUrl(provider: "discord" | "steam" | "dev", next: string): string {
  const query = new URLSearchParams({ next });
  if (provider === "steam") query.set("intent", "login");
  return `/auth/${provider}/?${query.toString()}`;
}

export function linkSteamUrl(next: string): string {
  return `/auth/steam/?${new URLSearchParams({ intent: "link", next }).toString()}`;
}
