import { Chip } from "@heroui/react";

import type { Side } from "../../live/types";

export const SIDE_NAME: Record<Side, string> = { hk: "The Hidden King", am: "The Archmother" };

const SIDE_CLASS: Record<Side, string> = {
  hk: "bg-team-hk-soft text-team-hk",
  am: "bg-team-am-soft text-team-am",
};

/** "The Hidden King · Pick 1", in the side's colour. */
export function SideChip({ side, detail }: { side: Side; detail?: string | null }) {
  return (
    <Chip size="sm" variant="soft" className={`font-semibold ${SIDE_CLASS[side]}`}>
      {detail ? `${SIDE_NAME[side]} · ${detail}` : SIDE_NAME[side]}
    </Chip>
  );
}
