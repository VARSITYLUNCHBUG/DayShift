import { Alert, AlertDialog, Button, Spinner } from "@heroui/react";
import { useState } from "react";
import type { ReactNode } from "react";

import { errorText } from "./toast";

interface Props {
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** danger for things that can't be undone. */
  tone?: "accent" | "danger" | "warning" | "success";
  /** May return a promise (an action's ack): the dialog waits, closes on success, and shows the
   * server's words on failure. */
  onConfirm: () => unknown;
}

/** A confirm step before an action, on HeroUI's AlertDialog. */
export function ActionDialog({
  isOpen,
  onOpenChange,
  title,
  children,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "accent",
  onConfirm,
}: Props) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const change = (open: boolean) => {
    if (pending) return;
    if (!open) setError(null);
    onOpenChange(open);
  };

  const confirm = async () => {
    setPending(true);
    setError(null);
    try {
      await onConfirm();
      setPending(false);
      onOpenChange(false);
    } catch (reason) {
      setPending(false);
      setError(errorText(reason));
    }
  };

  return (
    <AlertDialog.Backdrop isOpen={isOpen} onOpenChange={change}>
      <AlertDialog.Container size="sm">
        <AlertDialog.Dialog>
          <AlertDialog.Header>
            <AlertDialog.Icon status={tone} />
            <AlertDialog.Heading>{title}</AlertDialog.Heading>
          </AlertDialog.Header>
          <AlertDialog.Body className="flex flex-col gap-3">
            {children}
            {error ? (
              <Alert status="danger">
                <Alert.Indicator />
                <Alert.Content>
                  <Alert.Title>{error}</Alert.Title>
                </Alert.Content>
              </Alert>
            ) : null}
          </AlertDialog.Body>
          <AlertDialog.Footer>
            <Button variant="tertiary" onPress={() => change(false)} isDisabled={pending}>
              {cancelLabel}
            </Button>
            <Button
              variant={tone === "danger" ? "danger" : "primary"}
              onPress={() => void confirm()}
              isPending={pending}
            >
              {({ isPending }) => (
                <>
                  {isPending ? <Spinner color="current" size="sm" /> : null}
                  {confirmLabel}
                </>
              )}
            </Button>
          </AlertDialog.Footer>
        </AlertDialog.Dialog>
      </AlertDialog.Container>
    </AlertDialog.Backdrop>
  );
}
