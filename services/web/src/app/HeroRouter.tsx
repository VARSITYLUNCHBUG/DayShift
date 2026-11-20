import { RouterProvider } from "@heroui/react";
import type { ReactNode } from "react";
import { useHref, useNavigate } from "react-router";

const ABSOLUTE_URL = /^[a-z][a-z\d+.-]*:/i;

/** React Router resolves every href against the current route, which turns an external URL
 * such as https://deadlock.wiki into "/https:/deadlock.wiki". Absolute URLs pass through. */
function useAppHref(to: string): string {
  const href = useHref(to);
  return ABSOLUTE_URL.test(to) ? to : href;
}

/** HeroUI's links and menus navigate through React Router. */
export function HeroRouter({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  return (
    <RouterProvider navigate={(to, options) => void navigate(to, options)} useHref={useAppHref}>
      {children}
    </RouterProvider>
  );
}
