// The building blocks M6–M9 put together, each rendered from a fixture, on one page.
import { Button } from "@heroui/react";
import { useState } from "react";
import type { ReactNode } from "react";

import { ActionDialog } from "../components/ActionDialog";
import { ChoiceCard } from "../components/ChoiceCard";
import { DataTable } from "../components/DataTable";
import { HeroGrid, heroTags } from "../components/HeroGrid";
import { SideChip } from "../components/SideChip";
import { StatTile } from "../components/StatTile";
import { StatusChip } from "../components/StatusChip";
import { TeamPanel } from "../components/TeamPanel";
import { TierChip } from "../components/TierChip";
import { notify } from "../components/toast";
import { TurnBanner } from "../components/TurnBanner";
import { championSteps, TurnStrip } from "../components/TurnStrip";
import { number, teamName } from "../lib/format";
import type { MatchPlayer, MatchStatus } from "../../live/types";
import { STATUS_LABEL } from "../match/status";
import { fixture } from "./fixtures";
import { LivePreview } from "./LivePreview";

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold tracking-wide text-muted uppercase">{title}</h2>
      {children}
    </section>
  );
}

export function ComponentSheet() {
  const draft = fixture.match("champion_draft", "captain");
  const coinflip = fixture.match("coinflip", "captain");
  const done = fixture.match("completed", "player");
  const [picked, setPicked] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const turn = draft.turn;
  const statuses = Object.keys(STATUS_LABEL) as MatchStatus[];
  return (
    <LivePreview snaps={{}}>
    <main className="mx-auto flex max-w-7xl flex-col gap-10 px-4 py-8 sm:px-8">
      <h1 className="text-3xl font-bold">Components</h1>

      <Block title="TurnBanner, TurnStrip (champion_draft.captain)">
        <TurnBanner
          tone="hk"
          line={turn ? `${turn.action === "ban" ? "Ban" : "Pick"} ${turn.position} of ${turn.total} · Next: ${turn.next_captain_name ?? ""}` : null}
          title={turn?.action === "ban" ? "Your ban" : "Your pick"}
          deadline={draft.deadline_at}
          showBar
          actions={
            <Button size="lg" className="h-13 min-w-50 bg-success font-bold text-success-foreground" isDisabled={!picked}>
              Lock in
            </Button>
          }
        />
        <TurnStrip steps={championSteps(draft)} />
      </Block>

      <Block title="TeamPanel, HeroGrid (champion_draft.captain)">
        <div className="flex flex-wrap items-start gap-5">
          <TeamPanel match={draft} team="A" showHeroes />
          <div className="min-w-0 flex-999 basis-140">
            <HeroGrid champions={draft.champions} selectedId={picked} onSelect={setPicked} tags={heroTags(draft)} />
          </div>
          <TeamPanel match={draft} team="B" highlight showHeroes />
        </div>
      </Block>

      <Block title="ChoiceCard, SideChip (coinflip.captain)">
        <div className="grid grid-cols-2 gap-4">
          {(coinflip.coinflip?.options.length ? coinflip.coinflip.options : ["hk_pick1", "hk_pick2", "am_pick1", "am_pick2"]).map(
            (choice) => {
              const side = choice.startsWith("hk") ? "hk" : "am";
              return (
                <ChoiceCard
                  key={choice}
                  tone={side}
                  eyebrow={side === "hk" ? "The Hidden King" : "The Archmother"}
                  title={choice.endsWith("1") ? "Pick 1" : "Pick 2"}
                  onPress={() => notify.info(`Chose ${choice}`)}
                />
              );
            },
          )}
        </div>
        <div className="flex gap-2">
          <SideChip side="hk" detail="Pick 1" />
          <SideChip side="am" detail="Pick 2" />
        </div>
      </Block>

      <Block title="StatusChip (every status)">
        <div className="flex flex-wrap gap-2">
          {statuses.map((status) => (
            <StatusChip key={status} status={status} detail={status === "in_progress" ? "24:10" : null} />
          ))}
        </div>
      </Block>

      <Block title="StatTile, TierChip">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label="Rating" value="1,284" hint={<><TierChip tier="Diamond" /><span>#6</span></>} />
          <StatTile label="Record" value="27–19" hint="59%" />
          <StatTile label="MVP · Key" value="6 · 11" />
          <StatTile label="Strikes" value="1" hint="Next off in 2 clean matches" />
        </div>
        <div className="flex flex-wrap gap-2">
          {["Bronze", "Silver", "Gold", "Platinum", "Diamond", "Custom"].map((tier) => (
            <TierChip key={tier} tier={tier} />
          ))}
        </div>
      </Block>

      <Block title="DataTable (completed.player: rating changes)">
        <DataTable<MatchPlayer>
          label="Rating changes"
          rows={done.players}
          rowKey={(p) => p.id}
          columns={[
            { id: "name", header: "Player", isRowHeader: true, cell: (p) => <span className="font-semibold">{p.name}</span> },
            { id: "team", header: "Team", cell: (p) => (p.team ? teamName(done.team_names, p.team) : "") },
            { id: "rating", header: "Rating", align: "end", cell: (p) => number(p.rating) },
            {
              id: "delta",
              header: "Change",
              align: "end",
              cell: (p) => {
                const delta = done.result.deltas[p.id] ?? 0;
                return <span className={delta > 0 ? "text-success" : "text-muted"}>{delta > 0 ? `+${delta}` : delta}</span>;
              },
            },
          ]}
        />
      </Block>

      <Block title="ActionDialog, toast">
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onPress={() => setConfirming(true)}>
            Open a confirm dialog
          </Button>
          <Button variant="secondary" onPress={() => notify.error(new Error("That hero was just taken"))}>
            Error toast
          </Button>
          <Button variant="secondary" onPress={() => notify.success("Teams picked", "You're on P1's Team")}>
            Toast
          </Button>
        </div>
        <ActionDialog
          isOpen={confirming}
          onOpenChange={setConfirming}
          title="Leave the match?"
          tone="danger"
          confirmLabel="Leave"
          onConfirm={() => Promise.reject(new Error("This is the screen gallery: nothing was sent."))}
        >
          <p>You get a strike.</p>
        </ActionDialog>
      </Block>
    </main>
    </LivePreview>
  );
}
