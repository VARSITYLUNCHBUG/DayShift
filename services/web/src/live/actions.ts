// The websocket's actions, by name, with their arguments (protocol contract, "Actions").
// Every id is a string on the wire. The actor is always the signed-in player.
import type { CoinflipChoice } from "./protocol.gen";

type Empty = Record<string, never>;

export interface ActionArgs {
  "queue.join": Empty;
  "queue.leave": Empty;
  "lobby.ready": { match_id: string };
  "lobby.vote": { match_id: string; candidate_ids: string[] };
  "draft.pick_player": { match_id: string; step_index: number; player_id: string };
  "draft.coinflip": { match_id: string; choice: CoinflipChoice };
  "draft.champion": { match_id: string; step_index: number; champion_id: string };
  "draft.random_champion": { match_id: string; step_index: number };
  "draft.lobby_code": { match_id: string; code: string };
  "draft.api_start": { match_id: string };
  "results.confirm": { match_id: string };
  "results.dispute": { match_id: string; note: string };
  "ocr.map_row": { read_id: string; row: number; player_id: string };
  "early_leave.report": { match_id: string; player_id: string };
  "early_leave.answer": { match_id: string; agree: boolean };
  "subs.options": { match_id: string };
  "subs.request": { match_id: string; player_id: string };
  "subs.answer_request": { request_id: string; approve: boolean };
  "subs.cancel": { request_id: string };
  "subs.invite": { request_id: string; player_id: string };
  "subs.offer_queue": { request_id: string };
  "subs.answer_offer": { offer_id: string; accept: boolean };
  "scrims.claim": { match_id: string; side: string };
  "scrims.start": { match_id: string };
}

export type ActionName = keyof ActionArgs;

/** The server said no. `message` is plain text meant for the player. */
export class ActionRefused extends Error {
  override name = "ActionRefused";
}

/** The socket dropped before the ack came. Actions are never re-sent, so this one may or may
 * not have happened; the next snapshot says which. */
export class ConnectionLost extends Error {
  override name = "ConnectionLost";
  constructor(message = "Connection lost. Check the page and try again.") {
    super(message);
  }
}
