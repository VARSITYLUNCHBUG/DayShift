import { Button, Card, Spinner } from "@heroui/react";

import { useRandomDraft } from "../../../api/matches";
import { AppShell } from "../../components/AppShell";
import { EmptyState } from "../../components/EmptyState";
import { HeroCard } from "../../components/HeroCard";
import { SIDE_NAME } from "../../components/SideChip";
import { notify } from "../../components/toast";
import type { RandomDraft, Side } from "../../../live/types";

const SIDES: Side[] = ["hk", "am"];

const PANEL: Record<Side, { card: string; title: string }> = {
  hk: { card: "border-team-hk/40 bg-team-hk-soft", title: "text-team-hk" },
  am: { card: "border-team-am/40 bg-team-am-soft", title: "text-team-am" },
};

/** The draft as text, for pasting into Discord. */
export function draftText(draft: RandomDraft): string {
  return SIDES.map((side) => {
    const names = (list: { name: string }[]) => list.map((h) => h.name).join(", ") || "none";
    return `${SIDE_NAME[side]}: bans ${names(draft[side].bans)}; picks ${names(draft[side].picks)}`;
  }).join("\n");
}

/** 5.5 Random draft: every ban and pick in the mode's order, at random. Nothing is recorded. */
export function RandomDraftPage() {
  const roll = useRandomDraft();
  const again = () => roll.mutate(undefined, { onError: (error) => notify.error(error) });
  return (
    <AppShell>
      <RandomDraftView draft={roll.data ?? null} rolling={roll.isPending} onRoll={again} />
    </AppShell>
  );
}

interface ViewProps {
  draft: RandomDraft | null;
  rolling: boolean;
  onRoll: () => void;
}

export function RandomDraftView({ draft, rolling, onRoll }: ViewProps) {
  const copy = () => {
    if (!draft) return;
    const clipboard = typeof navigator !== "undefined" ? navigator.clipboard : undefined;
    if (!clipboard) {
      notify.warning("Copy isn't available here.");
      return;
    }
    clipboard.writeText(draftText(draft)).then(() => notify.success("Draft copied"), notify.error);
  };
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-3xl font-bold">Random draft</h1>
          <p className="text-sm text-muted">Every ban and pick at random, in the mode&apos;s order. Nothing is recorded.</p>
        </div>
        <div className="flex gap-2.5">
          {draft ? (
            <Button variant="outline" size="lg" className="h-12 font-semibold" onPress={copy}>
              Copy
            </Button>
          ) : null}
          <Button size="lg" className="h-12 px-6 font-bold" isPending={rolling} onPress={onRoll}>
            {({ isPending }) => (
              <>
                {isPending ? <Spinner color="current" size="sm" /> : null}
                {draft ? "Again" : "Roll"}
              </>
            )}
          </Button>
        </div>
      </div>
      {draft ? (
        <div className="flex flex-wrap gap-5">
          {SIDES.map((side) => (
            <SidePanel key={side} side={side} draft={draft} />
          ))}
        </div>
      ) : (
        <EmptyState title="No draft yet" description="Roll for a full set of bans and picks for both sides." />
      )}
    </div>
  );
}

function SidePanel({ side, draft }: { side: Side; draft: RandomDraft }) {
  const { bans, picks } = draft[side];
  const headingId = `random-${side}`;
  return (
    <Card aria-labelledby={headingId} className={`min-w-0 flex-1 basis-100 gap-4 border p-5.5 ${PANEL[side].card}`}>
      <h2 id={headingId} className={`text-lg font-bold ${PANEL[side].title}`}>
        {SIDE_NAME[side]}
      </h2>
      {bans.length > 0 ? (
        <section aria-label={`${SIDE_NAME[side]} bans`} className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-muted">Bans</h3>
          <ul className="grid grid-cols-4 gap-2 sm:grid-cols-6">
            {bans.map((hero) => (
              <li key={hero.id}>
                <HeroCard champion={hero} tone="danger" compact />
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <section aria-label={`${SIDE_NAME[side]} picks`} className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-muted">Picks</h3>
        <ul className="grid grid-cols-3 gap-2 sm:grid-cols-6">
          {picks.map((hero) => (
            <li key={hero.id}>
              <HeroCard champion={hero} tone={side} compact />
            </li>
          ))}
        </ul>
      </section>
    </Card>
  );
}
