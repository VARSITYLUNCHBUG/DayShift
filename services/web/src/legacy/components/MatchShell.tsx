import { createContext, useContext } from "react";
import type { ReactNode } from "react";

import { useSessionPlayer } from "../../api/session";
import { Sticker } from "../../components/Sticker";
import { roomPhase } from "../../components/shell/RoomHeader";
import { RoomShell } from "../../components/shell/RoomShell";
import type { MatchSnap, Viewer } from "../../live/types";

interface Props {
  /** With the viewer, the header says when they are only watching. */
  match: Pick<MatchSnap, "id" | "kind" | "status"> & { viewer?: Pick<Viewer, "is_player"> };
  children: ReactNode;
  /** More of the header's right side, after the match page's own (MatchChromeContext). */
  actions?: ReactNode;
  backTo?: string;
  backLabel?: string;
  width?: "narrow" | "wide";
}

/** What every phase's page shows besides its own content: the header's "Request a sub" and the
 * notices above the page while the match is paused for a sub. */
export interface MatchChrome {
  actions?: ReactNode;
  notices?: ReactNode;
}

export const MatchChromeContext = createContext<MatchChrome>({});

/** The old screens' match page, now drawn in the DayShift room shell (header, phase rail, stage).
 * FE-ROOM replaces each screen with the wireframe's scorebug, stage and rail. */
export function MatchShell({ match, children, actions, backTo = "/", backLabel = "Back to Play" }: Props) {
  const chrome = useContext(MatchChromeContext);
  const player = useSessionPlayer();
  const { phases, current } = roomPhase(match.status, match.kind);
  return (
    <RoomShell
      number={`No. ${match.id}`}
      phases={phases}
      current={current}
      back={{ to: backTo, label: backLabel }}
      me={player ? { name: player.name, avatar: player.avatar } : null}
      actions={
        <>
          {match.viewer && !match.viewer.is_player ? (
            <Sticker tone="raised" tilt="none">
              Watching
            </Sticker>
          ) : null}
          {chrome.actions}
          {actions}
        </>
      }
    >
      {chrome.notices}
      {children}
    </RoomShell>
  );
}
