// Friendly names over the generated protocol types, and the topic → snapshot mapping that
// useTopic is typed by. They come from protocol.legacy.ts (the old protocol) until FE-ROOM moves the
// screens to protocol.gen.ts, generated from the new schema; this file is not generated.
import type {
  Ack,
  LiveSnap,
  MatchSnap,
  MatchStatus,
  MeSnap,
  QueueSnap,
  ServerMessage,
} from "./protocol.legacy";

export type * from "./protocol.legacy";

export type MatchTopic = `match:${string}`;
export type Topic = "me" | "queue" | "live" | MatchTopic;

export type TopicData<T extends Topic> = T extends "me"
  ? MeSnap
  : T extends "queue"
    ? QueueSnap
    : T extends "live"
      ? LiveSnap
      : T extends MatchTopic
        ? MatchSnap
        : never;

export type AnySnap = MeSnap | QueueSnap | LiveSnap | MatchSnap;

/** Every status the server can send. Adding one to the schema breaks every exhaustive Record. */
export type { MatchStatus };

/** An ack. `result` comes only from the actions that return something (protocol contract). */
export type AckMessage = Ack & { result?: unknown };

export type SnapMessage = Extract<ServerMessage, { t: "snap" }>;

export function matchTopic(id: string): MatchTopic {
  return `match:${id}`;
}

export const MAX_TOPICS = 10;
