// Friendly names over the generated protocol types, and the topic → snapshot mapping that
// useTopic is typed by, over protocol.gen.ts (generated from Django's schema by `npm run gen`).
// This file is not generated.
import type {
  Ack,
  LiveSnap,
  MatchSnap,
  MatchStatus,
  MeSnap,
  QueueSnap,
  ServerMessage,
} from "./protocol.gen";

export type * from "./protocol.gen";

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
