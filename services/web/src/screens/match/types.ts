import type { ComponentType } from "react";

import type { MatchSnap } from "../../live/protocol.gen";

export interface MatchScreenProps {
  match: MatchSnap;
}

export type MatchScreen = ComponentType<MatchScreenProps>;
