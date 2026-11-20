// The app's toasts (P04 rung 4): news you don't have to act on. Bottom-left, 8 seconds, paused
// while hovered or focused (HeroUI's Toast; <ToastRegion /> is mounted once in the app). Never for
// something you must answer: that's a Dialog or a NoticeSheet.
import { toast } from "@heroui/react";

import { ActionRefused, ConnectionLost } from "../live/actions";

export const TOAST_MS = 8_000;

/** A button on the toast, such as "Open" to go to the match it's about. */
export interface ToastAction {
  label: string;
  onPress: () => void;
}

type Variant = "default" | "success" | "danger";

function show(variant: Variant, title: string, description?: string, action?: ToastAction): string {
  return toast(title, {
    variant,
    timeout: TOAST_MS,
    ...(description ? { description } : {}),
    ...(action ? { actionProps: { children: action.label, onPress: action.onPress, size: "sm" as const, variant: "outline" as const } } : {}),
  });
}

export const notify = {
  /** "You're in", "Teams picked", "Copied K7Q2PX". */
  info: (title: string, description?: string, action?: ToastAction): string => show("default", title, description, action),
  /** A success tick: "Steam linked". */
  success: (title: string, description?: string, action?: ToastAction): string => show("success", title, description, action),
  /** A refusal or failure, in the server's own plain words. */
  error: (reason: unknown): string => show("danger", errorText(reason)),
  /** Kept for the old screens: warnings are neutral in DayShift. */
  warning: (title: string, description?: string): string => show("default", title, description),
  close: (id: string): void => toast.close(id),
};

/** The words to show for a failure. Server refusals (DomainError.message) are shown as-is. */
export function errorText(reason: unknown): string {
  if (reason instanceof ActionRefused || reason instanceof ConnectionLost) return reason.message;
  if (reason instanceof Error && reason.message) return reason.message;
  return "That didn't work. Check your connection and try again.";
}
