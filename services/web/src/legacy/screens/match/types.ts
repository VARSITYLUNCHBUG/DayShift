import type { ComponentType } from "react";

import type { MatchSnap } from "../../../live/types";

export interface MatchScreenProps {
  match: MatchSnap;
}

export type MatchScreen = ComponentType<MatchScreenProps>;
