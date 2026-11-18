import type { z } from "zod";

/** An HTTP or shape failure from one of the dev APIs, with whatever body came back. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

interface ReviverContext {
  source?: string;
}

/**
 * Parse JSON, keeping integers too large for a double (Discord snowflakes) as their exact
 * digits. Uses the reviver `context.source` of modern engines; older ones fall back to
 * plain numbers.
 */
export function parseJson(text: string): unknown {
  return JSON.parse(text, (_key, value: unknown, context?: ReviverContext) => {
    if (typeof value === "number" && !Number.isSafeInteger(value) && Number.isInteger(value)) {
      return context?.source ?? value;
    }
    return value;
  });
}

export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  method?: Method;
  /** Sent as JSON. */
  body?: unknown;
  /** Sent as multipart/form-data instead of `body` (file uploads). */
  form?: FormData;
  query?: Record<string, string | number | undefined>;
  signal?: AbortSignal;
}

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

/**
 * The message in an error body: `{"error": {"code", "message"}}` from the control API, or
 * `{"error": "..."}` from the simulator.
 */
function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const error = (body as Record<string, unknown>).error;
    if (typeof error === "string" && error) return error;
    if (error && typeof error === "object") {
      const message = (error as Record<string, unknown>).message;
      if (typeof message === "string" && message) return message;
    }
  }
  if (typeof body === "string" && body.trim()) return body.trim().slice(0, 300);
  return fallback;
}

/** A tiny JSON client rooted at one prefix (`/_control/api`, `/_sim`). */
export class JsonClient {
  readonly base: string;
  private readonly fetcher: FetchLike;

  constructor(base: string, fetcher?: FetchLike) {
    this.base = base.replace(/\/+$/, "");
    this.fetcher = fetcher ?? ((input, init) => fetch(input, init));
  }

  url(path: string, query?: RequestOptions["query"]): string {
    const clean = path.replace(/^\/+/, "");
    let url = `${this.base}/${clean}`;
    if (query) {
      const params = new URLSearchParams();
      for (const [key, value] of Object.entries(query)) {
        if (value !== undefined) params.set(key, String(value));
      }
      const qs = params.toString();
      if (qs) url += `?${qs}`;
    }
    return url;
  }

  async raw(path: string, options: RequestOptions = {}): Promise<unknown> {
    const { method = "GET", body, form, query, signal } = options;
    const headers: Record<string, string> = { Accept: "application/json" };
    const init: RequestInit = { method, headers };
    if (signal) init.signal = signal;
    if (form) {
      // The browser sets the multipart Content-Type, with its boundary.
      init.body = form;
    } else if (body !== undefined) {
      init.body = JSON.stringify(body);
      headers["Content-Type"] = "application/json";
    }
    const response = await this.fetcher(this.url(path, query), init);
    const text = await response.text();
    let parsed: unknown = null;
    if (text) {
      try {
        parsed = parseJson(text);
      } catch {
        parsed = text;
      }
    }
    if (!response.ok) {
      const fallback = `${method} ${path} failed with ${response.status}`;
      throw new ApiError(errorMessage(parsed, fallback), response.status, parsed);
    }
    return parsed;
  }

  async call<T>(schema: z.ZodType<T>, path: string, options: RequestOptions = {}): Promise<T> {
    const body = await this.raw(path, options);
    const result = schema.safeParse(body);
    if (!result.success) {
      const issue = result.error.issues[0];
      const where = issue ? `${issue.path.join(".") || "(root)"}: ${issue.message}` : "bad shape";
      throw new ApiError(`Unexpected response from ${path}: ${where}`, 200, body);
    }
    return result.data;
  }
}
