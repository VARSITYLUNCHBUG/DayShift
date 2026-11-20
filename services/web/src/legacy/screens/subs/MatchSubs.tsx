import { Button } from "@heroui/react";
import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { MatchChromeContext } from "../../components/MatchShell";
import type { MatchSnap } from "../../../live/types";
import { SubNameDialog } from "./SubNameDialog";
import { SubNotices } from "./SubNotices";
import { SubRequestDialog } from "./SubRequestDialog";

/** Subs on every phase of a match page: "Request a sub" in the header (4.1), the paused and
 * approve notices above the page (4.6, 4.3), and the naming dialog (4.2), which opens straight
 * after you ask to sub yourself out and from the notice's "Name a sub". */
export function MatchSubs({ match, children }: { match: MatchSnap; children: ReactNode }) {
  const [requesting, setRequesting] = useState(false);
  const [naming, setNaming] = useState<string | null>(null);
  const stopNaming = useCallback(() => setNaming(null), []);
  const canRequest = match.viewer.can_request_sub;

  const chrome = useMemo(
    () => ({
      actions: canRequest ? (
        <Button variant="secondary" onPress={() => setRequesting(true)} className="h-11 rounded-xl font-semibold">
          Request a sub
        </Button>
      ) : null,
      notices: <SubNotices match={match} onName={setNaming} />,
    }),
    [canRequest, match],
  );

  return (
    <MatchChromeContext.Provider value={chrome}>
      {children}
      {canRequest || requesting ? (
        <SubRequestDialog
          match={match}
          isOpen={requesting && canRequest}
          onOpenChange={setRequesting}
          onRequested={(id, isSelf) => {
            if (isSelf) setNaming(id);
          }}
        />
      ) : null}
      <SubNameDialog match={match} requestId={naming} onClose={stopNaming} />
    </MatchChromeContext.Provider>
  );
}
