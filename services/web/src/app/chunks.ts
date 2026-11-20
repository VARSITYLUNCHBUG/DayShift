// The lazy page modules, by path: the routes load them, and link hovers warm them early.
/** The page chunks, by path, so a hover or focus on a link can start loading one early. */
export const PAGE_CHUNKS = {
  "/": () => import("../screens/play/Play"),
  "/matches": () => import("../screens/matches/Matches"),
  "/ladder": () => import("../screens/ladder/Ladder"),
  "/me": () => import("../screens/me/Me"),
  "/tools/random-draft": () => import("../screens/tools/Tools"),
  "/tools/scrims": () => import("../screens/tools/Tools"),
  "/link-steam": () => import("../screens/me/LinkSteam"),
  "/me/share": () => import("../screens/me/ShareCard"),
  postgame: () => import("../screens/postgame/PostgamePage"),
} as const;
