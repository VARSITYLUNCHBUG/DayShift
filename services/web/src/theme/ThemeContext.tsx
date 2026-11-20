import { useTheme } from "@heroui/react";
import { createContext, useContext, useEffect } from "react";
import type { ReactNode } from "react";

interface ThemeControl {
  isDark: boolean;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeControl>({ isDark: true, toggle: () => {} });

/** The app's one theme controller, on HeroUI's useTheme (it keeps the choice in localStorage
 * under "heroui-theme", which public/theme.js reads before the first paint). Dark unless the
 * player picks light. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const { resolvedTheme, setTheme } = useTheme("dark");
  const isDark = resolvedTheme !== "light";

  // The browser bar takes the ground colour (ink, or paper in the light theme).
  useEffect(() => {
    const ground = getComputedStyle(document.documentElement).getPropertyValue("--ds-ink").trim();
    if (ground) document.querySelector('meta[name="theme-color"]')?.setAttribute("content", ground);
  }, [isDark]);

  return <ThemeContext value={{ isDark, toggle: () => setTheme(isDark ? "light" : "dark") }}>{children}</ThemeContext>;
}

export function useThemeControl(): ThemeControl {
  return useContext(ThemeContext);
}
