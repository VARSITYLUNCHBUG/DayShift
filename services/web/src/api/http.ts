// Plain HTTP to Django: sign-in state, sign out, the result report, and the pages that aren't
// live. The websocket carries everything live.

/** Django's CSRF cookie, set by the SPA page and /api/session/. */
export function csrfToken(): string {
  const match = /(?:^|;\s*)csrftoken=([^;]+)/.exec(document.cookie);
  return match?.[1] ? decodeURIComponent(match[1]) : "";
}

export class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "HttpError";
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new HttpError(response.status, `${path} answered ${response.status}`);
  return (await response.json()) as T;
}

export async function post(path: string, body?: BodyInit): Promise<Response> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-CSRFToken": csrfToken(), Accept: "application/json" },
    body,
  });
  if (!response.ok) throw new HttpError(response.status, `${path} answered ${response.status}`);
  return response;
}

/** What a refusal says when the server gave no words of its own. */
const FAILED_TEXT: Record<number, string> = {
  401: "You're signed out. Sign in again to carry on.",
  403: "That didn't work. Refresh and try again.",
  404: "That match isn't here any more.",
  413: "That file is too large: the limit is 20 MB.",
};
const SERVER_TEXT = "Something went wrong on our side. Please try again.";

/** POSTs a form (multipart, so it can carry files) and reads the JSON answer. A refusal throws
 * an HttpError whose message is the server's own plain sentence (`{"error": "..."}`) when it
 * sent one: those are written for the player. */
export async function postForm<T>(path: string, form: FormData): Promise<T> {
  return postJson<T>(path, form);
}

/** POSTs (with the CSRF token) and reads the JSON answer, refusing as `postForm` does. */
export async function postJson<T>(path: string, body?: BodyInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken(), Accept: "application/json" },
      body,
    });
  } catch {
    throw new HttpError(0, "Couldn't reach the server. Check your connection and try again.");
  }
  const answer: unknown = await response.json().catch(() => null);
  if (response.ok) return answer as T;
  const error = answer && typeof answer === "object" && "error" in answer ? answer.error : null;
  // Sentences are for the player; short codes ("signed-out") are not.
  const sentence = typeof error === "string" && error.includes(" ") ? error : null;
  throw new HttpError(response.status, sentence ?? FAILED_TEXT[response.status] ?? SERVER_TEXT);
}
