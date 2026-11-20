// The pages' view of the live connection: your own state (`me`), the queue and the live matches,
// and the few actions the pages send, by name with their arguments.
import { useCallback, useEffect, useRef, useState } from "react";

import { useLive, useTopic } from "../live/hooks";
import type { TopicState } from "../live/hooks";
import type { LiveSnap, MatchSnap, MeSnap, QueueSnap } from "../live/protocol.gen";
import { matchTopic } from "../live/types";
import type { AckMessage } from "../live/types";

export type { LiveMatch, LiveSnap, MatchSnap, MeSnap, Offer, QueueSnap } from "../live/protocol.gen";

export interface Live<T> {
  data: T | undefined;
  state: TopicState;
}

/** Your own live state: queue place, cooldown, match, offers. Only ever yours. */
export function useMe(): Live<MeSnap> {
  return useTopic("me");
}

/** Who's in the queue (names, never the order). */
export function useQueue(): Live<QueueSnap> {
  return useTopic("queue");
}

/** Every match being played now, scrims included. */
export function useLiveMatches(): Live<LiveSnap> {
  return useTopic("live");
}

/** One match's snapshot, for the notices that need it (Ready Up). Pass null to watch nothing. */
export function useMatchSnap(id: string | null): Live<MatchSnap> {
  return useTopic(id === null ? null : matchTopic(id));
}

/** The actions the pages outside the match room send. */
export interface PageActionArgs {
  "queue.join": Record<string, never>;
  "queue.leave": Record<string, never>;
  "queue.let_go": Record<string, never>;
  "lobby.ready": { match_id: string };
  "subs.answer_offer": { offer_id: string; accept: boolean };
}

export type PageAction = keyof PageActionArgs;

type Send = (name: string, args: object) => Promise<AckMessage>;

export interface PageActions {
  /** Sends it; settles with the ack, after the snapshots it caused. Rejects with the server's
   * own refusal (ActionRefused) or ConnectionLost. */
  run: <N extends PageAction>(name: N, args: PageActionArgs[N]) => Promise<AckMessage>;
  /** The action in flight, for pending labels. */
  pending: PageAction | null;
}

export function usePageAction(): PageActions {
  const live = useLive();
  const [pending, setPending] = useState<PageAction | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(
    <N extends PageAction>(name: N, args: PageActionArgs[N]): Promise<AckMessage> => {
      setPending(name);
      const send = live.act.bind(live) as unknown as Send;
      const settle = () => {
        if (mounted.current) setPending((current) => (current === name ? null : current));
      };
      return send(name, args).then(
        (ack) => {
          settle();
          return ack;
        },
        (reason: unknown) => {
          settle();
          throw reason;
        },
      );
    },
    [live],
  );
  return { run, pending };
}
