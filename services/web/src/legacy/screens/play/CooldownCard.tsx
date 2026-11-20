import { Button, Card, Chip } from "@heroui/react";

import { Countdown } from "../../components/Countdown";
import { plural } from "../../lib/format";
import type { Cooldown, PenaltyKind } from "../../../live/types";

const KIND: Record<PenaltyKind, string> = {
  missed_ready: "Missed ready check",
  dodge: "Left the lobby",
  leaver: "Left the game",
  false_report: "Wrong result",
  manual: "Staff cooldown",
};

/** 1.6: on a queue cooldown. The queue opens again when the clock runs out. */
export function CooldownCard({ cooldown }: { cooldown: Cooldown }) {
  const strikes = cooldown.strikes;
  return (
    <Card aria-labelledby="cooldown-title" className="gap-4.5 rounded-3xl border border-border p-5 sm:p-7">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-muted">Ranked queue</span>
        <Chip size="sm" color="danger" variant="soft" className="font-semibold">
          {KIND[cooldown.kind]}
        </Chip>
      </div>
      <div className="flex flex-col gap-1">
        <span id="cooldown-title" className="text-sm text-muted">
          Queue opens in
        </span>
        <Countdown deadline={cooldown.until} className="text-5xl font-bold tracking-tight" />
      </div>
      {strikes > 0 ? (
        <div className="flex flex-wrap items-center gap-2.5 text-sm">
          <span className="flex gap-1" role="img" aria-label={plural(strikes, "strike")}>
            {Array.from({ length: strikes + 1 }, (_, i) => (
              <span key={i} className={`size-2.5 rounded-full ${i < strikes ? "bg-danger" : "bg-default"}`} />
            ))}
          </span>
          <span>{plural(strikes, "strike")}</span>
          {cooldown.games_to_next !== null ? (
            <>
              <span className="text-muted" aria-hidden="true">
                ·
              </span>
              <span className="text-muted">
                next off in {plural(cooldown.games_to_next, "clean match", "clean matches")}
              </span>
            </>
          ) : null}
        </div>
      ) : null}
      <Button size="lg" fullWidth isDisabled variant="secondary" className="mt-auto h-13 text-base font-bold">
        Join queue
      </Button>
    </Card>
  );
}
