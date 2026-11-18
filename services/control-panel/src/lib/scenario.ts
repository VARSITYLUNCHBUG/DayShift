import type { ScenarioStep } from "../api";

const record = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;

/** The step's call, `POST matches/latest/advance`. */
export function stepCall(step: ScenarioStep): string {
  const method = typeof step.method === "string" ? step.method.toUpperCase() : "?";
  const path = typeof step.path === "string" ? step.path : "?";
  return `${method} ${path}`;
}

/** The step's title, if it has one. */
export function stepTitle(step: ScenarioStep): string | null {
  return typeof step.title === "string" && step.title ? step.title : null;
}

/** The step's body, compact for a list row. */
export function stepBody(step: ScenarioStep): string {
  // Nothing to show for no body, or the {} the server fills in.
  const body = record(step.body);
  if (step.body == null || (body !== null && Object.keys(body).length === 0)) return "";
  const text = JSON.stringify(step.body);
  return text.length > 160 ? `${text.slice(0, 157)}…` : text;
}

/** What a step should end with: an HTTP status, and the match's status for match calls. */
export interface Expectation {
  http: number | null;
  status: string | null;
}

/**
 * A step's own `expect` (`{"status": "player_draft", "http": 409}`, both optional), or what its
 * call implies: an advance with `until` ends at that status. Null: any success will do.
 */
export function expectationOf(step: ScenarioStep): Expectation | null {
  const own = record(step.expect);
  if (own) {
    return {
      http: typeof own.http === "number" ? own.http : null,
      status: typeof own.status === "string" ? own.status : null,
    };
  }
  const until = record(step.body)?.until;
  if (typeof step.path === "string" && step.path.endsWith("/advance") && typeof until === "string") {
    return { http: null, status: until };
  }
  return null;
}

/** What a step did: its HTTP status, and the match's status after it when the answer has one. */
export interface Outcome {
  http: number;
  status: string | null;
}

export function outcomeOf(http: number, response: unknown): Outcome {
  const body = record(response);
  const match = record(body?.match);
  const status = typeof match?.status === "string" ? match.status : typeof body?.to === "string" ? body.to : null;
  return { http, status };
}

/** Whether the outcome is what the step expected (any 2xx when it names no status code). */
export function meets(expected: Expectation | null, outcome: Outcome): boolean {
  const httpOk = expected?.http != null ? outcome.http === expected.http : outcome.http < 400;
  const statusOk = expected?.status != null ? outcome.status === expected.status : true;
  return httpOk && statusOk;
}

export function describeExpectation(expected: Expectation | null): string {
  if (!expected) return "success";
  const parts = [expected.http != null ? `HTTP ${expected.http}` : "success"];
  if (expected.status) parts.push(`match ${expected.status}`);
  return parts.join(", ");
}

export function describeOutcome(outcome: Outcome): string {
  return outcome.status ? `HTTP ${outcome.http}, match ${outcome.status}` : `HTTP ${outcome.http}`;
}
