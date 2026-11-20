import { vi } from "vitest";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Stubs fetch with answers by exact URL: a body to send as JSON, or a function making the
 * Response. Anything else is a 404, as Django would say it. */
export function serveHttp(answers: Record<string, unknown>) {
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    const answer = answers[url];
    if (answer === undefined) return Promise.resolve(json({ error: "not-found" }, 404));
    return Promise.resolve(typeof answer === "function" ? (answer as (i?: RequestInit) => Response)(init) : json(answer));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

export { json };
