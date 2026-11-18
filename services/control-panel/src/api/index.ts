/** The panel's single entry point to both backends. Screens import from here only. */
import { createControlApi } from "./control";
import { createSimApi } from "./sim";

export const control = createControlApi();
export const sim = createSimApi();

export { ApiError } from "./http";
export { ACTIONS, COINFLIP_CHOICES } from "./control";
export type { Action, AdvanceResult, CreatePlayersInput, LobbyMode, MatchScript, PlayerRef, Via } from "./control";
export { subscribeEvents } from "./sim";
export type { MessageTarget, ModalSubmit, StreamStatus } from "./sim";
export type * from "./schemas";
