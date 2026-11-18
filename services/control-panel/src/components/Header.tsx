import { AlertDialog, Button, Chip, Description, Input, Label, Spinner, TextField, Tooltip } from "@heroui/react";
import { useState } from "react";

import type { ControlState } from "../api";

export interface Health {
  ok: boolean | null;
  detail: string;
}

function HealthChip({ name, health }: { name: string; health: Health }) {
  const color = health.ok === null ? "default" : health.ok ? "success" : "danger";
  const dot = health.ok === null ? "bg-muted" : health.ok ? "bg-success" : "bg-danger";
  return (
    <Tooltip delay={200}>
      <Tooltip.Trigger>
        <Chip size="sm" variant="soft" color={color} aria-label={`${name}: ${health.detail}`}>
          <span className={`mr-1 inline-block size-2 rounded-full ${dot}`} />
          {name}
        </Chip>
      </Tooltip.Trigger>
      <Tooltip.Content placement="bottom">{health.detail}</Tooltip.Content>
    </Tooltip>
  );
}

function ResetButton({ onReset }: { onReset: (fixture: string) => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const [fixture, setFixture] = useState("dev_default");
  const [busy, setBusy] = useState(false);
  const confirm = async () => {
    setBusy(true);
    try {
      await onReset(fixture.trim());
    } finally {
      setBusy(false);
      setOpen(false);
    }
  };
  return (
    <>
      <Button size="sm" variant="danger-soft" onPress={() => { setOpen(true); }}>
        Reset…
      </Button>
      <AlertDialog.Backdrop isOpen={open} onOpenChange={setOpen}>
        <AlertDialog.Container size="sm">
          <AlertDialog.Dialog>
            <AlertDialog.Header>
              <AlertDialog.Icon status="danger" />
              <AlertDialog.Heading>Reset the dev stack?</AlertDialog.Heading>
            </AlertDialog.Header>
            <AlertDialog.Body className="flex flex-col gap-3">
              <p>
                This resets the Discord simulator, empties the league tables and loads the dev
                fixtures again. Every fake player, queue entry and match you made is gone. Admin
                logins survive.
              </p>
              <TextField value={fixture} onChange={setFixture}>
                <Label>Fixture</Label>
                <Input variant="secondary" className="mono" />
                <Description>dev_default, or none for just the community and season</Description>
              </TextField>
            </AlertDialog.Body>
            <AlertDialog.Footer>
              <Button slot="close" variant="tertiary">
                Cancel
              </Button>
              <Button variant="danger" isPending={busy} onPress={() => void confirm()}>
                {({ isPending }) => (
                  <>
                    {isPending ? <Spinner color="current" size="sm" /> : null}
                    Reset everything
                  </>
                )}
              </Button>
            </AlertDialog.Footer>
          </AlertDialog.Dialog>
        </AlertDialog.Container>
      </AlertDialog.Backdrop>
    </>
  );
}

interface Props {
  state: ControlState | undefined;
  web: Health;
  sim: Health;
  bot: Health;
  onReset: (fixture: string) => Promise<unknown>;
  onPauseTimers: () => void;
  onResumeTimers: () => void;
}

/** Top bar: environment badge, what's loaded, service health, global actions. */
export function Header({ state, web, sim, bot, onReset, onPauseTimers, onResumeTimers }: Props) {
  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-border bg-surface px-4 py-2">
      <div className="flex items-center gap-2">
        <span className="text-base font-semibold">draft-bot control</span>
        <Chip size="sm" color="danger" variant="primary" className="font-bold tracking-wider">
          DEV ONLY
        </Chip>
      </div>
      <div className="flex items-center gap-2 text-muted">
        {state ? (
          state.community ? (
            <span>
              {state.community.name}
              {state.season !== null ? ` · season ${state.season}` : ""}
              {state.mode ? ` · ${state.mode}` : ""}
            </span>
          ) : (
            <span className="text-warning">no community yet: run dev_seed, or Reset</span>
          )
        ) : null}
        {state?.timersPaused ? (
          <Chip size="sm" color="warning" variant="soft">
            timers paused
          </Chip>
        ) : null}
      </div>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        <HealthChip name="web" health={web} />
        <HealthChip name="sim" health={sim} />
        <HealthChip name="bot" health={bot} />
        <Button size="sm" variant="tertiary" onPress={onPauseTimers}>
          Pause timers
        </Button>
        <Button size="sm" variant="tertiary" onPress={onResumeTimers}>
          Resume timers
        </Button>
        <ResetButton onReset={onReset} />
      </div>
    </header>
  );
}
