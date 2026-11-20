import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { fixture } from "../dev/fixtures";
import { renderPage } from "../../test/render";
import { Countdown, CountdownBar, CountdownRing } from "./Countdown";

describe("Countdown", () => {
  it("counts down to the deadline by the server's clock", async () => {
    // The fixture's server clock says 19:00:19; the ready check closes at 19:03:00.
    const match = fixture.match("ready_check", "player");
    renderPage(<Countdown deadline={match.deadline_at} />);
    expect(await screen.findByText(/^2:4[01]$/)).toBeInTheDocument();
  });

  it("says it's waiting for the server once the time is up", async () => {
    renderPage(<Countdown deadline="2026-01-05T19:00:00.000Z" />);
    expect(await screen.findByText("Waiting for server")).toBeInTheDocument();
  });

  it("renders nothing without a deadline", () => {
    const { container } = renderPage(<Countdown deadline={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("draws the time left as a bar and a ring", async () => {
    const match = fixture.match("ready_check", "player");
    renderPage(
      <>
        <CountdownBar deadline={match.deadline_at} label="Time left" />
        <CountdownRing deadline={match.deadline_at} caption="7 / 12" />
      </>,
    );
    expect(await screen.findByRole("progressbar", { name: "Time left" })).toBeInTheDocument();
    expect(await screen.findByRole("progressbar", { name: /^2:4[01] left$/ })).toBeInTheDocument();
    expect(screen.getByText("7 / 12")).toBeInTheDocument();
  });
});
