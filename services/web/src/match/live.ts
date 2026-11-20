// The match room's view of the live connection, typed by the generated protocol (protocol.gen.ts).
// The shared hooks in src/live are still typed by the old protocol for the other screens, so the
// room reads its topic and sends its actions through these instead.
import { useCallback, useEffect, useRef, useState } from "react";

import { useLive, useTopic } from "../live/hooks";
import type { TopicState } from "../live/hooks";
import type { ActionArgs as WireArgs, MatchSnap } from "../live/protocol.gen";
import { matchTopic } from "../live/types";
import type { AckMessage } from "../live/types";

/** Every action, by name, with its arguments. The generator writes bounded lists as tuples;
 * the room sends plain lists, which the server checks again. */
export type MatchActionArgs = Omit<WireArgs, "wish.set" | "lobby.vote"> & {
  "wish.set": { match_id: string; champion_ids: string[] };
  "lobby.vote": { match_id: string; candidate_ids: string[] };
};

export type MatchActionName = keyof MatchActionArgs;

type Send = (name: string, args: object) => Promise<AckMessage>;

export interface MatchResult {
  match: MatchSnap | undefined;
  state: TopicState;
}

/** The match's live snapshot. */
export function useMatchTopic(id: string | null): MatchResult {
  const { data, state } = useTopic(id === null ? null : matchTopic(id));
  return { match: data, state };
}

export interface MatchAction {
  /** Sends the action; settles with its ack (after the snapshots it caused). Rejects with the
   * server's refusal (ActionRefused) or ConnectionLost. */
  run: <N extends MatchActionName>(name: N, args: MatchActionArgs[N]) => Promise<AckMessage>;
  /** The action in flight, if any: buttons show their pending label from it. */
  pending: MatchActionName | null;
}

/** Runs room actions over the socket, one at a time per caller. */
export function useMatchAction(): MatchAction {
  const live = useLive();
  const [pending, setPending] = useState<MatchActionName | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(
    <N extends MatchActionName>(name: N, args: MatchActionArgs[N]): Promise<AckMessage> => {
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
