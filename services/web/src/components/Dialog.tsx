import { Modal } from "@heroui/react";
import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { Countdown } from "./Countdown";
import type { TeamKey } from "./team";
import { TEAM_CLASS } from "./team";

interface Props {
  isOpen: boolean;
  /** Called with false when the player backs out (Esc, Go back). Never called for a must-answer
   * dialog, which only closes when the server moves on. */
  onOpenChange?: (open: boolean) => void;
  title: ReactNode;
  /** A short line above the title: "No. 413 · Wednesday league night". */
  eyebrow?: ReactNode;
  /** The answer's server deadline: a 56px clock under the title. */
  deadline?: string | null;
  /** Colours the border, eyebrow and clock (a team's turn); neutral by default. */
  tone?: TeamKey | null;
  /** Ready Up: no Esc and no click outside; you answer it. Confirm dialogs leave this off, so Esc
   * means Go back. */
  mustAnswer?: boolean;
  /** Finishes the clock's 30 s and 10 s announcements ("to ready up"). */
  announce?: string;
  children?: ReactNode;
  /** The buttons; give the main one autoFocus so focus lands on it (F07). */
  actions: ReactNode;
  className?: string;
}

/** A modal (P04 rung 1): only for what must be answered now (Ready Up, a destructive confirm).
 * Centred over the dimmed page, 520 wide (full width minus 16 on phones), traps focus and hands
 * it back afterwards. HeroUI's Modal on React Aria. */
export function Dialog({ isOpen, onOpenChange, title, eyebrow, deadline, tone = null, mustAnswer = false, announce, children, actions, className }: Props) {
  return (
    <Modal.Backdrop
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!mustAnswer) onOpenChange?.(open);
      }}
      isDismissable={!mustAnswer}
      isKeyboardDismissDisabled={mustAnswer}
    >
      <Modal.Container placement="center" className="p-2 sm:p-10">
        <Modal.Dialog
          className={cn(
            "w-full max-w-dialog",
            tone && TEAM_CLASS[tone].border,
            className,
          )}
        >
          <Modal.Header className="gap-3">
            {eyebrow ? <span className={cn("text-label font-bold", tone ? TEAM_CLASS[tone].text : "text-muted")}>{eyebrow}</span> : null}
            <Modal.Heading>{title}</Modal.Heading>
          </Modal.Header>
          {deadline ? <Countdown deadline={deadline} size="dialog" tone={tone} announce={announce} /> : null}
          {children ? <Modal.Body className="flex flex-col gap-3 p-0 text-body text-muted">{children}</Modal.Body> : null}
          <Modal.Footer className="flex flex-wrap justify-start gap-2.5 p-0">{actions}</Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
