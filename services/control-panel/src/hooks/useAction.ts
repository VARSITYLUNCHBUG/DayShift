import { toast } from "@heroui/react";
import { useCallback, useState } from "react";

import { ApiError } from "../api";

export function describeError(err: unknown): string {
  if (err instanceof ApiError) return err.status >= 400 ? `${err.status}: ${err.message}` : err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

/**
 * Wrap an API call for a button: tracks the pending label, toasts the outcome (`success` can
 * describe the result), and runs `after` (usually a poll refresh) either way. Resolves to the
 * result, or undefined when the call failed.
 */
export function useAction(after?: () => void) {
  const [pending, setPending] = useState<string | null>(null);

  const run = useCallback(
    async <T,>(
      label: string,
      call: () => Promise<T>,
      success?: string | ((result: T) => string),
    ): Promise<T | undefined> => {
      setPending(label);
      try {
        const result = await call();
        const message = typeof success === "function" ? success(result) : (success ?? `${label}: done`);
        toast.success(message, { timeout: 2500 });
        return result;
      } catch (err) {
        toast.danger(label, { description: describeError(err), timeout: 8000 });
        return undefined;
      } finally {
        setPending(null);
        after?.();
      }
    },
    [after],
  );

  return { pending, run };
}

/** The `run` a screen passes down to the parts that make API calls. */
export type Run = ReturnType<typeof useAction>["run"];
