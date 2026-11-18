import { describe, expect, it } from "vitest";

import { describeExpectation, describeOutcome, expectationOf, meets, outcomeOf, stepBody } from "./scenario";

describe("stepBody", () => {
  it("shows a body compactly, and nothing for an empty one", () => {
    expect(stepBody({ path: "queue/join", body: { count: 12 } })).toBe('{"count":12}');
    expect(stepBody({ path: "reset", body: {} })).toBe("");
    expect(stepBody({ path: "reset" })).toBe("");
  });
});

describe("scenario expectations", () => {
  it("reads a step's own expect, or what an advance implies", () => {
    expect(expectationOf({ path: "matches/latest/fire", expect: { status: "captain_phase", http: 200 } })).toEqual({
      http: 200,
      status: "captain_phase",
    });
    expect(expectationOf({ path: "matches/latest/advance", body: { until: "coinflip" } })).toEqual({ http: null, status: "coinflip" });
    expect(expectationOf({ path: "queue/join", body: { count: 12 } })).toBeNull();
  });

  it("finds the match status in the answer", () => {
    expect(outcomeOf(200, { match: { status: "player_draft" }, from: "ready_check", to: "player_draft" })).toEqual({ http: 200, status: "player_draft" });
    expect(outcomeOf(200, { from: "a", to: "lobby_code" })).toEqual({ http: 200, status: "lobby_code" });
    expect(outcomeOf(409, { error: { code: "invalid_action" } })).toEqual({ http: 409, status: null });
  });

  it("compares expected with actual", () => {
    expect(meets(null, { http: 201, status: null })).toBe(true);
    expect(meets(null, { http: 409, status: null })).toBe(false);
    expect(meets({ http: 409, status: null }, { http: 409, status: null })).toBe(true);
    expect(meets({ http: null, status: "coinflip" }, { http: 200, status: "player_draft" })).toBe(false);
    expect(describeExpectation({ http: null, status: "coinflip" })).toBe("success, match coinflip");
    expect(describeOutcome({ http: 200, status: "player_draft" })).toBe("HTTP 200, match player_draft");
  });
});
