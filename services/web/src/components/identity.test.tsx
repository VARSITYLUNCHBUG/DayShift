import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "../test/render";
import { Avatar } from "./Avatar";
import { HomeLink, Lockup, Mark } from "./Brand";
import { Icon } from "./Icon";
import { Portrait } from "./Portrait";
import { Badge, Sticker, Tag } from "./Sticker";
import { Who } from "./Who";

describe("Brand", () => {
  it("draws the lockup as one image named DayShift, and the mark as decoration", () => {
    const { container } = render(
      <>
        <Lockup />
        <Mark />
      </>,
    );
    expect(screen.getByRole("img", { name: "DayShift" })).toBeInTheDocument();
    expect(container.querySelectorAll('svg[aria-hidden="true"]')).toHaveLength(1);
  });

  it("links home with the lockup", () => {
    renderPage(<HomeLink />, { live: false });
    expect(screen.getByRole("link", { name: "DayShift, home" })).toHaveAttribute("href", "/");
  });
});

describe("Icon", () => {
  it("is decorative unless it's given a label", () => {
    const { container } = render(<Icon name="copy" />);
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    render(<Icon name="alert" label="Warning" />);
    expect(screen.getByRole("img", { name: "Warning" })).toBeInTheDocument();
  });
});

describe("Stickers and tags", () => {
  it("puts the clan tag in the team's colour inside a match, neutral outside", () => {
    render(
      <>
        <Tag team="hk">OWL</Tag>
        <Tag>KRK</Tag>
        <Sticker tone="danger">Banned</Sticker>
        <Badge label="3 unread">3</Badge>
      </>,
    );
    expect(screen.getByText("OWL")).toHaveClass("bg-team-hk");
    expect(screen.getByText("KRK")).toHaveClass("bg-raised");
    expect(screen.getByText("Banned")).toHaveClass("bg-danger", "shadow-sticker");
    expect(screen.getByLabelText("3 unread")).toHaveTextContent("3");
  });

  it("shows tag, name and the quiet you marker", () => {
    render(<Who name="Rook" tag="OWL" team="hk" isYou />);
    expect(screen.getByText("Rook")).toBeInTheDocument();
    expect(screen.getByText("you")).toBeInTheDocument();
    expect(screen.getByText("OWL")).toHaveClass("bg-team-hk");
  });
});

describe("Avatar", () => {
  it("shows initials when there's no picture, and a tick once ready", async () => {
    render(<Avatar name="Grey Talon" team="am" ready />);
    await vi.waitFor(() => expect(document.querySelector('[data-glyphs="GT"]')).toBeInTheDocument());
    expect(screen.getByRole("img", { name: "ready" })).toBeInTheDocument();
  });
});

describe("Portrait", () => {
  it("falls back to initials when the art won't load", () => {
    const { container } = render(<Portrait hero="Lady Geist" src="/static/hero-art/lady-geist.webp" team="am" />);
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    fireEvent.error(img!);
    expect(document.querySelector('[data-glyphs="LG"]')).toBeInTheDocument();
  });
});
