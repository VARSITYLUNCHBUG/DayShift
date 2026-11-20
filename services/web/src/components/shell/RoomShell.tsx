import type { ReactNode } from "react";

import { useIsPhone } from "../../lib/useMediaQuery";
import type { TeamKey } from "../team";
import { ConnectionBanner } from "./ConnectionBanner";
import { PhoneRoomTop, RoomHeader } from "./RoomHeader";
import type { ShellUser } from "./TopBar";
import { SiteFooter } from "./SiteFooter";

interface Props {
  /** "No. 413". */
  number: ReactNode;
  /** "Wednesday league night". */
  title?: ReactNode;
  phases: readonly string[];
  current: number;
  /** The acting team: the rail's current bar and the phone phase line take its colour. */
  tone?: TeamKey | null;
  /** The phone top's phase line: "Heroes · your pick". The rail's label by default. */
  phaseLine?: ReactNode;
  /** The step's deadline, for the phone top's clock. */
  deadline?: string | null;
  /** Need a sub, Watching. */
  actions?: ReactNode;
  me?: ShellUser | null;
  /** Where the mark goes: Play by default. */
  back?: { to: string; label: string };
  /** A banner for the match's state (paused for a sub); the connection banner is built in. */
  banner?: ReactNode;
  /** Desktop: the Scorebug (or final sides) under the header. */
  bug?: ReactNode;
  /** Phone: the TurnBanner at the top of the stage instead. */
  phoneBug?: ReactNode;
  /** The chat or context rail; under the stage below 1024, its own view on phones. */
  rail?: ReactNode;
  /** The phase's one action on phones, in a sticky footer. On desktop it lives in the bug. */
  footer?: ReactNode;
  /** The stage: the phase's work. */
  children: ReactNode;
}

/** The match room (ds.room_page, P01): header with the phase rail, the scorebug, the stage and the
 * rail. On phones: the phone room top, the turn banner, the stage and a sticky footer action. */
export function RoomShell({
  number,
  title,
  phases,
  current,
  tone = null,
  phaseLine,
  deadline,
  actions,
  me,
  back,
  banner,
  bug,
  phoneBug,
  rail,
  footer,
  children,
}: Props) {
  const phone = useIsPhone();
  return (
    <div className="flex min-h-dvh flex-col">
      {phone ? (
        <PhoneRoomTop number={number} phase={phaseLine ?? phases[current]} tone={tone} deadline={deadline} actions={actions} back={back} />
      ) : (
        <RoomHeader number={number} title={title} phases={phases} current={current} tone={tone} actions={actions} me={me} back={back} />
      )}
      <ConnectionBanner />
      {banner}
      {phone ? null : bug}
      <main
        id="stage"
        tabIndex={-1}
        className={
          phone
            ? "flex flex-1 flex-col gap-3.5 px-4 pt-4 outline-none " + "pb-8"
            : "mx-auto box-border flex w-full max-w-room flex-1 flex-wrap items-start gap-x-8 gap-y-7 px-8 pt-7 pb-14 outline-none"
        }
      >
        {phone ? phoneBug : null}
        <div className="flex min-w-0 flex-col gap-7 md:flex-999 md:basis-160">{children}</div>
        {rail ? <aside className="flex min-w-0 flex-1 basis-80 flex-col gap-5">{rail}</aside> : null}
      </main>
      <SiteFooter />
      {phone && footer ? (
        <div data-sticky-footer className="fixed inset-x-0 bottom-0 z-30 flex gap-2.5 border-t border-line bg-background px-4 pt-3 pb-bar-safe *:flex-1">{footer}</div>
      ) : null}
    </div>
  );
}
