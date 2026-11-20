import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { QueryKey } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

/** HTTP answers from fixtures instead of Django, for screens that fetch (the result screen's
 * match record). Each answer counts as fresh for a very long time, so the screen's own query
 * never asks the server. */
export function HttpPreview({ answers, children }: { answers: [QueryKey, unknown][]; children: ReactNode }) {
  const [client] = useState(() => {
    const preview = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
    const forever = Date.now() + 10 * 365 * 24 * 60 * 60 * 1000;
    for (const [key, data] of answers) preview.setQueryData(key, data, { updatedAt: forever });
    return preview;
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
