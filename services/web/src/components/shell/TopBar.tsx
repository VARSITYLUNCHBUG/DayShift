import { lazy, Suspense } from "react";
import type { ReactNode } from "react";
import { Link, NavLink } from "react-router";

import { cn } from "../../lib/cn";
import { useThemeControl } from "../../theme/ThemeContext";
import { Avatar } from "../Avatar";
import { HomeLink } from "../Brand";
import { ButtonLink, IconButton } from "../Button";
import { Icon } from "../Icon";

const MoreMenu = lazy(() => import("./MoreMenu"));

export interface ShellUser {
  name: string;
  avatar?: string | null;
}

/** The main nav (ds.NAV). Tools moves into More on phones, where Me takes its tab. */
export const NAV = [
  { label: "Play", to: "/", end: true },
  { label: "Matches", to: "/matches" },
  { label: "Ladder", to: "/ladder" },
  { label: "Tools", to: "/tools/random-draft" },
] as const;

export const PHONE_NAV = [
  { label: "Play", to: "/", end: true },
  { label: "Matches", to: "/matches" },
  { label: "Ladder", to: "/ladder" },
  { label: "Me", to: "/me" },
] as const;

/** Light or dark, one press. */
export function ThemeSwitch() {
  const theme = useThemeControl();
  return (
    <IconButton
      kind="quiet"
      icon={theme.isDark ? "sun" : "moon"}
      label={theme.isDark ? "Switch to the light theme" : "Switch to the dark theme"}
      onPress={theme.toggle}
    />
  );
}

function MeLink({ me }: { me: ShellUser }) {
  return (
    <Link to="/me" className="flex min-h-11 items-center gap-2.5 rounded-full pr-1 text-body font-bold">
      <Avatar name={me.name} src={me.avatar} size="md" />
      <span className="sr-only">Me:</span>{" "}
      <span className="max-w-40 truncate max-lg:sr-only">{me.name}</span>
    </Link>
  );
}

interface TopBarProps {
  /** Signed out: a Sign in button instead of you. */
  me: ShellUser | null;
  /** The status chip: what you're in right now. */
  status?: ReactNode;
}

/** The desktop top bar (ds.topbar): the lockup home, the main nav, the status chip, you. */
export function TopBar({ me, status }: TopBarProps) {
  return (
    <header className="flex flex-wrap items-center gap-x-7 gap-y-3 border-b border-line px-8 py-3">
      <HomeLink />
      <nav aria-label="Main">
        <ul className="flex flex-wrap gap-1">
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={"end" in item ? item.end : false}
                className={({ isActive }) =>
                  cn(
                    "flex h-11 items-center rounded-full px-4 text-body transition-state",
                    isActive
                      ? "bg-brand font-extrabold text-brand-ink"
                      : "font-semibold text-muted hover:text-foreground",
                  )
                }
              >
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <div className="ml-auto flex min-h-11 items-center gap-3.5">
        {status}
        <ThemeSwitch />
        {me ? <MeLink me={me} /> : <ButtonLink to="/signin" size="sm">Sign in</ButtonLink>}
      </div>
    </header>
  );
}

/** The phone top bar (ds.phone_top): the lockup, or Back with a title; More on the right. */
export function PhoneTop({ title, back, right }: { title?: ReactNode; back?: string; right?: ReactNode }) {
  return (
    <header className="flex min-h-14 items-center gap-2 border-b border-line px-3 py-1.5">
      {back ? (
        <Link to={back} aria-label="Back" className="flex size-11 items-center justify-center rounded-full">
          <Icon name="back" size={22} />
        </Link>
      ) : (
        <HomeLink size={20} />
      )}
      {title ? <b className="truncate text-body font-extrabold">{title}</b> : null}
      <div className="ml-auto flex items-center gap-2">
        {right}
        <Suspense fallback={<span className="size-11" />}>
          <MoreMenu />
        </Suspense>
      </div>
    </header>
  );
}

/** The phone tab bar (ds.phone_tabs): Play, Matches, Ladder, Me. The current tab is bubblegum. */
export function PhoneTabs() {
  return (
    <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface pb-safe">
      <ul className="flex">
        {PHONE_NAV.map((item) => (
          <li key={item.to} className="flex-1">
            <NavLink
              to={item.to}
              end={"end" in item ? item.end : false}
              className={({ isActive }) =>
                cn(
                  "flex h-14 items-center justify-center text-label transition-state",
                  isActive ? "font-extrabold text-brand shadow-tab-active" : "font-semibold text-muted",
                )
              }
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** A page's main action on a phone: stuck to the bottom (above the tab bar in the app shell), after
 * the content in the DOM. On desktop it sits where it is. */
export function StickyFooter({ children, aboveTabs = true }: { children: ReactNode; aboveTabs?: boolean }) {
  return (
    <div
      className={cn(
        "flex gap-2.5 max-md:fixed max-md:inset-x-0 max-md:z-30 max-md:border-t max-md:border-line max-md:bg-background max-md:px-4 max-md:py-3 max-md:*:flex-1",
        aboveTabs ? "max-md:bottom-14" : "max-md:bottom-0",
      )}
    >
      {children}
    </div>
  );
}
