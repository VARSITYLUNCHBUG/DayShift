/** Typed calls to the Discord simulator's control API under `/_sim/` (services/discord-sim). */
import { JsonClient, parseJson, type FetchLike } from "./http";
import { AnyJson, SimAttachment, SimEvent, SimHealth, SimInteraction, SimMessageList, SimState } from "./schemas";

export interface ComponentClick {
  user_id: string;
  message_id: string;
  custom_id: string;
  values?: string[];
}

/**
 * A modal submit, keyed by each field's custom_id: text and select answers, and for file
 * uploads attachment ids (from `uploadAttachment`) or `{filename}` for a placeholder image.
 */
export interface ModalSubmit {
  user_id: string;
  custom_id: string;
  values: Record<string, string | string[]>;
  attachments: Record<string, (string | { filename: string })[]>;
}

/** How long a click waits for a followup after the bot answers: where refusals arrive. */
const FOLLOWUP_WAIT = 1;

/** Where a fake user's chat message goes: a guild channel, or their DM with the bot. */
export type MessageTarget = { channel_id: string } | { dm: true };

/** The SSE `event:` names the sim sends: one per log entry kind. */
export const EVENT_KINDS = ["rest", "gateway", "control"] as const;

export type StreamStatus = "connecting" | "open" | "closed";

export function createSimApi(base = "/_sim", fetcher?: FetchLike) {
  const http = new JsonClient(base, fetcher);
  return {
    health: (signal?: AbortSignal) => http.call(SimHealth, "health", signal ? { signal } : {}),
    state: (signal?: AbortSignal) => http.call(SimState, "state", signal ? { signal } : {}),
    channelMessages: (channelId: string, limit = 50, signal?: AbortSignal) =>
      http.call(SimMessageList, `channels/${channelId}/messages`, {
        query: { limit },
        ...(signal ? { signal } : {}),
      }),
    userDms: (userId: string, limit = 50, signal?: AbortSignal) =>
      http.call(SimMessageList, `users/${userId}/dms`, { query: { limit }, ...(signal ? { signal } : {}) }),
    clickComponent: (click: ComponentClick) =>
      http.call(SimInteraction, "interactions/component", {
        method: "POST",
        body: { ...click, followup_wait: FOLLOWUP_WAIT },
      }),
    submitModal: (submit: ModalSubmit) =>
      http.call(SimInteraction, "interactions/modal", {
        method: "POST",
        body: { ...submit, followup_wait: FOLLOWUP_WAIT },
      }),
    /** Store a file as the sim's CDN would, ahead of a modal that names it. */
    uploadAttachment: (file: Blob, filename: string) => {
      const form = new FormData();
      form.append("file", file, filename);
      return http.call(SimAttachment, "attachments", { method: "POST", form });
    },
    sendMessage: (userId: string, target: MessageTarget, content: string) =>
      http.call(AnyJson, "messages", { method: "POST", body: { user_id: userId, ...target, content } }),
    eventsUrl: () => http.url("events"),
  };
}

/** Parse one SSE `data:` payload into a log event, or null if it isn't one. */
export function parseEventData(data: string): SimEvent | null {
  let value: unknown;
  try {
    value = parseJson(data);
  } catch {
    return null;
  }
  const parsed = SimEvent.safeParse(value);
  return parsed.success ? parsed.data : null;
}

/**
 * Follow `/_sim/events`. The browser's EventSource reconnects by itself (resuming from the
 * last event id); the returned function closes the stream.
 */
export function subscribeEvents(
  url: string,
  onEvent: (event: SimEvent) => void,
  onStatus: (status: StreamStatus) => void,
): () => void {
  const source = new EventSource(url);
  onStatus("connecting");
  const handle = (message: MessageEvent<string>) => {
    const event = parseEventData(message.data);
    if (event) onEvent(event);
  };
  source.onopen = () => {
    onStatus("open");
  };
  source.onerror = () => {
    onStatus(source.readyState === EventSource.CLOSED ? "closed" : "connecting");
  };
  source.onmessage = handle;
  for (const kind of EVENT_KINDS) source.addEventListener(kind, handle);
  return () => {
    source.close();
    onStatus("closed");
  };
}
