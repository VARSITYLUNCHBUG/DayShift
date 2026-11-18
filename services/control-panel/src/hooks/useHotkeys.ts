import { useEffect, useLayoutEffect, useRef } from "react";

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

function inDialog(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.closest("[role=dialog], [role=alertdialog], [role=menu], [role=listbox]") !== null;
}

/** Single-key shortcuts (no modifiers) that stay quiet while you type in a field or a dialog is open. */
export function useHotkeys(bindings: Record<string, () => void>) {
  const ref = useRef(bindings);
  useLayoutEffect(() => {
    ref.current = bindings;
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey || isTyping(event.target) || inDialog(event.target)) return;
      const handler = ref.current[event.key];
      if (handler) {
        event.preventDefault();
        handler();
      }
    };
    // Capture: React Aria lists (the tabs, menus) take letters and digits for typeahead first.
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
    };
  }, []);
}
