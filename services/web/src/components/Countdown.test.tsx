import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnnouncerProvider, useAnnounce } from "./Announcer";
import { Countdown, WAITING } from "./Countdown";

const START = new Date("2026-11-18T21:14:00Z").getTime();

function at(seconds: number): string {
  return new Date(START + seconds * 1000).toISOString();
}

function announced(): string {
  return document.getElementById("announce")?.textContent ?? "";
}

describe("Countdown", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(START);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("is a timer counting m:ss to the server's deadline", () => {
    render(<Countdown deadline={at(272)} />);
    expect(screen.getByRole("timer")).toHaveTextContent("4:32");
    expect(screen.getByRole("timer")).toHaveAccessibleName("Time left 4:32");
  });

  it("never goes below zero: at 0:00 it waits for the server", () => {
    render(<Countdown deadline={at(2)} size="scorebug" tone="hk" />);
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(screen.getByRole("timer")).toHaveTextContent(WAITING);
    expect(screen.getByRole("timer")).not.toHaveTextContent("-");
  });

  it("announces at 30 and 10 seconds through the shared live region, once each", () => {
    render(
      <AnnouncerProvider>
        <Countdown deadline={at(32)} announce="to pick" />
      </AnnouncerProvider>,
    );
    expect(announced()).toBe("");
    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(announced()).toBe("30 seconds left to pick");
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(announced()).toBe("10 seconds left to pick");
  });

  it("stays quiet without `announce`", () => {
    render(
      <AnnouncerProvider>
        <Countdown deadline={at(31)} />
      </AnnouncerProvider>,
    );
    act(() => {
      vi.advanceTimersByTime(25_000);
    });
    expect(announced()).toBe("");
  });

  it("draws nothing without a deadline", () => {
    const { container } = render(<Countdown deadline={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

function Say({ words }: { words: string }) {
  const announce = useAnnounce();
  return (
    <button type="button" onClick={() => announce(words)}>
      say
    </button>
  );
}

describe("Announcer", () => {
  it("is the page's one polite region", () => {
    vi.useFakeTimers();
    render(
      <AnnouncerProvider>
        <Say words="Vesper picked Infernus." />
      </AnnouncerProvider>,
    );
    const region = document.getElementById("announce");
    expect(region).toHaveAttribute("aria-live", "polite");
    act(() => {
      screen.getByRole("button").click();
      vi.advanceTimersByTime(100);
    });
    expect(region).toHaveTextContent("Vesper picked Infernus.");
    vi.useRealTimers();
  });
});
