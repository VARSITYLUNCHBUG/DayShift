// PlayerTile, ChoiceCard, ActionDialog, StatTile, StatusChip, TierChip, DataTable, EmptyState and
// the toast helper.
import { Toast } from "@heroui/react";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { fixture } from "../dev/fixtures";
import { ActionRefused } from "../../live/actions";
import type { MatchPlayer, MatchStatus } from "../../live/types";
import { STATUS_LABEL } from "../match/status";
import { renderPage } from "../../test/render";
import { ActionDialog } from "./ActionDialog";
import { ChoiceCard } from "./ChoiceCard";
import { DataTable } from "./DataTable";
import { EmptyState } from "./EmptyState";
import { PlayerTile } from "./PlayerTile";
import { StatTile } from "./StatTile";
import { StatusChip } from "./StatusChip";
import { TierChip } from "./TierChip";
import { notify } from "./toast";

describe("PlayerTile", () => {
  it("ticks ready players and marks the rest", () => {
    const [ready, waiting] = [
      fixture.match("ready_check", "player").players.find((p) => p.is_ready)!,
      fixture.match("ready_check", "player").players.find((p) => !p.is_ready)!,
    ];
    renderPage(
      <ul>
        <li>
          <PlayerTile name={ready.name} state="ready" />
        </li>
        <li>
          <PlayerTile name={waiting.name} state="waiting" detail="1,240" />
        </li>
      </ul>,
      { live: false },
    );
    const [first, second] = screen.getAllByRole("listitem");
    expect(within(first!).getByRole("img", { name: "Ready" })).toBeInTheDocument();
    expect(within(second!).getByRole("img", { name: "Not ready" })).toBeInTheDocument();
    expect(second).toHaveTextContent("1,240");
  });
});

describe("ChoiceCard", () => {
  it("is a big button for one choice", async () => {
    const options = fixture.match("coinflip", "captain").coinflip?.options ?? [];
    const onPress = vi.fn();
    renderPage(<ChoiceCard tone="hk" eyebrow="The Hidden King" title="Pick 1" onPress={onPress} />, { live: false });
    await userEvent.click(screen.getByRole("button", { name: /The Hidden King\s*Pick 1/ }));
    expect(onPress).toHaveBeenCalledTimes(1);
    expect(Array.isArray(options)).toBe(true);
  });
});

describe("ActionDialog", () => {
  it("waits for the action, and shows the server's words when it's refused", async () => {
    const onOpenChange = vi.fn();
    const onConfirm = vi.fn().mockRejectedValue(new ActionRefused("You can't leave now."));
    renderPage(
      <ActionDialog isOpen onOpenChange={onOpenChange} title="Leave the match?" confirmLabel="Leave" tone="danger" onConfirm={onConfirm}>
        <p>You get a strike.</p>
      </ActionDialog>,
      { live: false },
    );
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Leave the match?");
    await userEvent.click(screen.getByRole("button", { name: "Leave" }));
    expect(await screen.findByText("You can't leave now.")).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("closes once the action is done", async () => {
    const onOpenChange = vi.fn();
    renderPage(
      <ActionDialog isOpen onOpenChange={onOpenChange} title="Confirm?" confirmLabel="Confirm" onConfirm={() => Promise.resolve()} />,
      { live: false },
    );
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await vi.waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });
});

describe("StatTile and TierChip", () => {
  it("shows a stat with its tier", () => {
    renderPage(<StatTile label="Rating" value="1,284" hint={<TierChip tier="Diamond" />} />, { live: false });
    expect(screen.getByText("Rating")).toBeInTheDocument();
    expect(screen.getByText("1,284")).toBeInTheDocument();
    expect(screen.getByText("Diamond")).toBeInTheDocument();
  });

  it("shows nothing without a tier", () => {
    const { container } = renderPage(<TierChip tier={null} />, { live: false });
    expect(container).toBeEmptyDOMElement();
  });
});

describe("StatusChip", () => {
  it("has a label for every status in the fixtures", () => {
    const statuses = new Set<MatchStatus>(
      ["ready_check", "captain_phase", "player_draft", "coinflip", "champion_draft", "lobby_code", "in_progress", "completed"].map(
        (scenario) => fixture.match(scenario, "spectator").status,
      ),
    );
    renderPage(
      <>
        {[...statuses].map((status) => (
          <StatusChip key={status} status={status} />
        ))}
        <StatusChip status="in_progress" detail="24:10" />
      </>,
      { live: false },
    );
    for (const status of statuses) expect(screen.getAllByText(STATUS_LABEL[status]).length).toBeGreaterThan(0);
    expect(screen.getByText("In game · 24:10")).toBeInTheDocument();
  });
});

describe("DataTable", () => {
  it("renders rows and columns", () => {
    const match = fixture.match("completed", "player");
    renderPage(
      <DataTable<MatchPlayer>
        label="Rating changes"
        rows={match.players}
        rowKey={(p) => p.id}
        columns={[
          { id: "name", header: "Player", isRowHeader: true, cell: (p) => p.name },
          { id: "delta", header: "Change", align: "end", cell: (p) => String(match.result.deltas[p.id] ?? 0) },
        ]}
      />,
      { live: false },
    );
    const table = screen.getByRole("grid", { name: "Rating changes" });
    expect(within(table).getAllByRole("row")).toHaveLength(match.players.length + 1);
    expect(within(table).getByRole("rowheader", { name: "P1" })).toBeInTheDocument();
  });

  it("says when it's empty", () => {
    renderPage(<DataTable label="Nothing" rows={[]} rowKey={() => ""} columns={[{ id: "a", header: "A", isRowHeader: true, cell: () => "" }]} empty="No matches yet" />, {
      live: false,
    });
    expect(screen.getByText("No matches yet")).toBeInTheDocument();
  });
});

describe("EmptyState", () => {
  it("shows a title, description and action", () => {
    renderPage(<EmptyState title="No matches right now" description="Check back soon" action={<button type="button">Go</button>} />, {
      live: false,
    });
    expect(screen.getByText("No matches right now")).toBeInTheDocument();
    expect(screen.getByText("Check back soon")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Go" })).toBeInTheDocument();
  });
});

describe("toast", () => {
  it("shows a refusal in the server's words", async () => {
    renderPage(<Toast.Provider />, { live: false });
    notify.error(new ActionRefused("That hero was just taken"));
    expect(await screen.findByText("That hero was just taken")).toBeInTheDocument();
  });
});
