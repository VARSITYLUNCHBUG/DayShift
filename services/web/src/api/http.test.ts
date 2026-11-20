import { afterEach, describe, expect, it, vi } from "vitest";

import { HttpError, postForm } from "./http";

function respond(status: number, body: string) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(body, { status }))));
}

async function refusal(): Promise<HttpError> {
  try {
    await postForm("/api/x/", new FormData());
  } catch (reason) {
    if (reason instanceof HttpError) return reason;
  }
  throw new Error("Expected an HttpError");
}

afterEach(() => vi.unstubAllGlobals());

describe("postForm", () => {
  it("passes the server's own sentence on", async () => {
    respond(400, JSON.stringify({ error: "Only a captain can do that." }));
    const error = await refusal();
    expect([error.status, error.message]).toEqual([400, "Only a captain can do that."]);
  });

  it("puts words to a refusal code or a page with no JSON", async () => {
    respond(401, JSON.stringify({ error: "signed-out" }));
    expect((await refusal()).message).toBe("You're signed out. Sign in again to carry on.");
    respond(413, "<html>Request Entity Too Large</html>");
    expect((await refusal()).message).toBe("That file is too large: the limit is 20 MB.");
    respond(500, "");
    expect((await refusal()).message).toBe("Something went wrong on our side. Please try again.");
  });

  it("says when the server can't be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    expect((await refusal()).status).toBe(0);
  });
});
