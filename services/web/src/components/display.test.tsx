import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { HK_PLAYERS, SOUL_LEAD } from "../dev/sample";
import { renderPage } from "../test/render";
import { Bar, DataTable, ScoreLine, StackedBar, StatTile } from "./Data";
import { PageHeader, Panel, Section } from "./Layout";
import { LeadChart } from "./LeadChart";
import { PageTabs, Segmented, SkipLink, StatusChip } from "./Navigation";
import { EmptyState, ErrorState, Skeleton } from "./States";

describe("States", () => {
  it("say what's empty, what's loading and what failed", () => {
    render(
      <>
        <EmptyState title="No matches tonight yet">The first one starts when 12 are in the queue.</EmptyState>
        <Skeleton label="Loading the ladder" />
        <ErrorState title="We couldn't save your wishes" code="No. 413">
          Try again.
        </ErrorState>
      </>,
    );
    expect(screen.getByText("No matches tonight yet")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Loading the ladder" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("We couldn't save your wishes");
  });
});

describe("Data", () => {
  it("shows a stat with its label and a score line in both teams' colours", () => {
    render(
      <>
        <StatTile label="Your rating" value="1,512" line="+17" />
        <ScoreLine label="Kills" hk="41" am="27" />
      </>,
    );
    expect(screen.getByText("1,512")).toHaveClass("tabular-nums");
    expect(screen.getByText("41")).toHaveClass("text-team-hk");
    expect(screen.getByText("27")).toHaveClass("text-team-am");
  });

  it("is a real table with a caption, row headers and your row tinted", () => {
    render(
      <DataTable
        caption="Rook's Team scoreboard"
        rows={HK_PLAYERS}
        rowKey={(row) => row.id}
        highlight={(row) => row.name === "Rook"}
        columns={[
          { key: "player", header: "Player", isRowHeader: true, cell: (row) => row.name },
          { key: "hero", header: "Hero", cell: (row) => row.hero, align: "right" },
        ]}
      />,
    );
    const table = screen.getByRole("table", { name: "Rook's Team scoreboard" });
    expect(within(table).getAllByRole("columnheader")).toHaveLength(2);
    expect(within(table).getByRole("rowheader", { name: "Rook" }).closest("tr")).toHaveClass("bg-raised");
  });

  it("draws bars as decoration and the lead chart as one labelled image", () => {
    const { container } = render(
      <>
        <Bar value={39} max={50} tone="hk" />
        <StackedBar parts={[{ share: 0.5, tone: "hk" }, { share: 0.5, tone: "am" }]} />
        <LeadChart points={SOUL_LEAD} label="Souls lead. Rook's Team led from 9:00." />
      </>,
    );
    expect(container.querySelectorAll('[aria-hidden="true"]').length).toBeGreaterThanOrEqual(3);
    expect(screen.getByRole("img", { name: "Souls lead. Rook's Team led from 9:00." })).toBeInTheDocument();
  });
});

describe("Layout", () => {
  it("titles sections and pages", () => {
    render(
      <>
        <PageHeader title="Ladder" lead="Season 1" />
        <Section title="Tonight">
          <Panel>Two matches</Panel>
        </Section>
      </>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Ladder" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Tonight" })).toHaveTextContent("Two matches");
  });
});

function SegmentedHarness() {
  const [value, setValue] = useState<"summary" | "timeline">("summary");
  return (
    <>
      <Segmented
        label="View"
        value={value}
        onChange={setValue}
        options={[
          { id: "summary", label: "Summary" },
          { id: "timeline", label: "Timeline" },
        ]}
      />
      <output>{value}</output>
    </>
  );
}

describe("Navigation", () => {
  it("links the status chip back to what you're in", () => {
    renderPage(<StatusChip to="/matches/413">No. 413 · Your pick</StatusChip>, { live: false });
    expect(screen.getByRole("link", { name: "No. 413 · Your pick" })).toHaveAttribute("href", "/matches/413");
  });

  it("marks the current page tab", () => {
    renderPage(
      <PageTabs
        label="Postgame"
        items={[
          { label: "Summary", to: "/matches/413", end: true },
          { label: "Timeline", to: "/matches/413/timeline" },
        ]}
      />,
      { live: false, route: "/matches/413/timeline" },
    );
    const nav = screen.getByRole("navigation", { name: "Postgame" });
    expect(within(nav).getByRole("link", { name: "Timeline" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Summary" })).not.toHaveAttribute("aria-current");
  });

  it("switches a segmented control", async () => {
    render(<SegmentedHarness />);
    await userEvent.click(screen.getByRole("radio", { name: "Timeline" }));
    expect(screen.getByRole("status")).toHaveTextContent("timeline");
  });

  it("skips to the content", () => {
    render(<SkipLink />);
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
  });
});
