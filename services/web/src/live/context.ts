import { createContext } from "react";

import type { LiveSocket } from "./LiveSocket";

export const LiveContext = createContext<LiveSocket | null>(null);
