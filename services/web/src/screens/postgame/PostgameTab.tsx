import { useParams } from "react-router";

import { useSessionPlayer } from "../../api/session";
import { ButtonLink } from "../../components/Button";
import { PageTabs } from "../../components/Navigation";
import { RANKED_PHASES } from "../../components/shell/RoomHeader";
import { RoomShell } from "../../components/shell/RoomShell";
import { EmptyState } from "../../components/States";

export type PostgameTabName = "timeline" | "replay" | "advanced";

const TITLE: Record<PostgameTabName, string> = {
  timeline: "Timeline",
  replay: "Replay",
  advanced: "Advanced",
};

/** The postgame tabs past the summary (R08 to R10): one deliberate click deeper each. FE-PAGES
 * fills them from the match's deadlock-api stats. */
export default function PostgameTab({ tab }: { tab: PostgameTabName }) {
  const { id = "" } = useParams();
  const player = useSessionPlayer();
  return (
    <RoomShell
      number={`No. ${id}`}
      phases={RANKED_PHASES}
      current={RANKED_PHASES.length - 1}
      me={player ? { name: player.name, avatar: player.avatar } : null}
    >
      <PageTabs
        label="Postgame"
        items={[
          { label: "Summary", to: `/matches/${id}`, end: true },
          { label: "Timeline", to: `/matches/${id}/timeline` },
          { label: "Replay", to: `/matches/${id}/replay` },
          { label: "Advanced", to: `/matches/${id}/advanced` },
        ]}
      />
      <h1 className="sr-only">
        No. {id}: {TITLE[tab]}
      </h1>
      <EmptyState
        title={`The ${TITLE[tab].toLowerCase()} isn't in yet`}
        action={
          <ButtonLink to={`/matches/${id}`} kind="ghost">
            Back to the summary
          </ButtonLink>
        }
      >
        Stats come from deadlock-api a few minutes after the match ends.
      </EmptyState>
    </RoomShell>
  );
}
