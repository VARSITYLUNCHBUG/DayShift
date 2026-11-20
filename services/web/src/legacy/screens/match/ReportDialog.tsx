import { Picture } from "@gravity-ui/icons";
import {
  Alert,
  Button,
  Form,
  Input,
  Label,
  ListBox,
  Modal,
  Select,
  Spinner,
  TextField,
  ToggleButton,
} from "@heroui/react";
import type { Key } from "@heroui/react";
import { useEffect, useState } from "react";
import { DropZone, FileTrigger, Text } from "react-aria-components";

import { REPORT_THANKS, SCREENSHOT_TYPES, screenshotProblem, useReport } from "../../../api/report";
import { SIDE_NAME } from "../../components/SideChip";
import { errorText, notify } from "../../components/toast";
import { teamName } from "../../lib/format";
import { teamPlayers } from "../../match/draft";
import type { MatchPlayer, MatchSnap, Side, Team } from "../../../live/types";

interface Props {
  match: MatchSnap;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

/** 3.2 Report result: who won, the scoreboard screenshot, and what Discord's report form also
 * asks for (the Deadlock match ID, MVP and key players). One captain's screenshot is enough;
 * the other captain can add theirs from the confirm step. */
export function ReportDialog({ match, isOpen, onOpenChange }: Props) {
  return (
    <Modal.Backdrop isOpen={isOpen} onOpenChange={onOpenChange}>
      <Modal.Container size="md" scroll="inside">
        <Modal.Dialog>
          {({ close }) => (
            <>
              <Modal.CloseTrigger aria-label="Close" />
              <Modal.Header>
                <Modal.Heading>Report result</Modal.Heading>
              </Modal.Header>
              <Modal.Body>
                <ReportForm match={match} onDone={close} />
              </Modal.Body>
            </>
          )}
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}

const WINNER_TONE: Record<Side, { on: string; side: string }> = {
  hk: { on: "border-team-hk bg-team-hk-soft text-team-hk-soft-foreground", side: "text-team-hk" },
  am: { on: "border-team-am bg-team-am-soft text-team-am-soft-foreground", side: "text-team-am" },
};

interface Shot {
  file: File;
  url: string | null;
}

function previewUrl(file: File): string | null {
  return typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : null;
}

function size(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

function ReportForm({ match, onDone }: { match: MatchSnap; onDone: () => void }) {
  const report = useReport(match.id);
  const [winner, setWinner] = useState<Team | null>(null);
  const [shot, setShot] = useState<Shot | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [deadlockId, setDeadlockId] = useState("");
  const [mvp, setMvp] = useState<string | null>(null);
  const [keys, setKeys] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  // The preview's object URL lives as long as it shows.
  const url = shot?.url;
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [url],
  );

  const roster: MatchPlayer[] = [...teamPlayers(match, "A"), ...teamPlayers(match, "B")];
  const pick = (file: File) => {
    setShot({ file, url: previewUrl(file) });
    setProblem(screenshotProblem(file));
    setError(null);
  };
  const toggleKey = (id: string, on: boolean) => {
    setKeys((current) => {
      if (!on) return current.filter((k) => k !== id);
      // Two at most: the newest choice replaces the oldest.
      return [...current.slice(-1), id];
    });
  };
  const chooseMvp = (key: Key | null) => {
    const id = key === null || key === "none" ? null : String(key);
    setMvp(id);
    // The MVP is the MVP, not a key player too (as on Discord).
    if (id) setKeys((current) => current.filter((k) => k !== id));
  };

  const ready = winner !== null && shot !== null && problem === null;
  const submit = () => {
    if (!ready) return;
    setError(null);
    report.mutate(
      { winner, image: shot.file, deadlockMatchId: deadlockId, mvp, keys },
      {
        onSuccess: (done) => {
          notify.success(REPORT_THANKS[done.status] ?? "Thanks: result received.");
          onDone();
        },
        onError: (reason) => setError(errorText(reason)),
      },
    );
  };

  return (
    <Form
      className="flex flex-col gap-5.5"
      validationBehavior="aria"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div role="group" aria-labelledby={`winner-${match.id}`} className="flex flex-col gap-2">
        <span id={`winner-${match.id}`} className="text-sm text-muted">
          Winner
        </span>
        <div className="grid grid-cols-2 gap-2.5">
          {(["A", "B"] as const).map((team) => {
            const side = match.sides[team];
            const tone = side ? WINNER_TONE[side] : null;
            const selected = winner === team;
            return (
              <ToggleButton
                key={team}
                isSelected={selected}
                onChange={() => {
                  setWinner(team);
                  setError(null);
                }}
                className={`flex h-18 w-full flex-col items-center justify-center gap-0.5 rounded-2xl border-2 text-base font-bold whitespace-normal ${
                  selected ? (tone?.on ?? "border-accent bg-accent-soft text-accent-soft-foreground") : "border-border bg-background text-foreground"
                }`}
              >
                <span>{teamName(match.team_names, team)}</span>
                {side ? <span className={`text-xs font-semibold ${tone?.side ?? ""}`}>{SIDE_NAME[side]}</span> : null}
              </ToggleButton>
            );
          })}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span id={`shot-${match.id}`} className="text-sm text-muted">
          Scoreboard screenshot
        </span>
        <DropZone
          aria-labelledby={`shot-${match.id}`}
          getDropOperation={(types) => (SCREENSHOT_TYPES.some((type) => types.has(type)) ? "copy" : "cancel")}
          onDrop={async (event) => {
            const item = event.items.find((i) => i.kind === "file");
            if (item?.kind === "file") pick(await item.getFile());
          }}
          className={({ isDropTarget, isFocusVisible }) =>
            `flex items-center gap-3.5 rounded-2xl border p-3 outline-none ${
              isDropTarget ? "border-accent bg-accent-soft" : problem ? "border-danger bg-background" : "border-border bg-background"
            } ${isFocusVisible ? "ring-2 ring-focus" : ""}`
          }
        >
          {shot?.url ? (
            <img src={shot.url} alt="Your screenshot" className="h-14 w-16 shrink-0 rounded-lg object-cover sm:w-24" />
          ) : (
            <span className="flex h-14 w-16 shrink-0 items-center justify-center rounded-lg bg-surface-tertiary text-muted sm:w-24">
              <Picture width={22} height={22} aria-hidden="true" />
            </span>
          )}
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            {shot ? (
              <>
                <Text slot="label" className="truncate text-sm font-semibold">
                  {shot.file.name}
                </Text>
                <span className={`text-sm ${problem ? "text-danger" : "text-muted"}`}>{problem ?? size(shot.file.size)}</span>
              </>
            ) : (
              <Text slot="label" className="text-sm text-muted">
                Drop or paste it here. PNG, JPEG or WebP, up to 20 MB.
              </Text>
            )}
          </span>
          <FileTrigger
            acceptedFileTypes={SCREENSHOT_TYPES}
            onSelect={(files) => {
              const file = files?.[0];
              if (file) pick(file);
            }}
          >
            <Button variant="secondary" size="sm" className="h-11 shrink-0">
              {shot ? "Replace" : "Choose"}
            </Button>
          </FileTrigger>
        </DropZone>
      </div>

      <TextField name="deadlock_match_id" value={deadlockId} onChange={setDeadlockId} fullWidth>
        <Label>
          Deadlock match ID <span className="text-muted">(optional)</span>
        </Label>
        <Input variant="secondary" inputMode="numeric" autoComplete="off" maxLength={18} className="h-12" />
      </TextField>

      <Select placeholder="No MVP" value={mvp ?? "none"} onChange={chooseMvp} variant="secondary" fullWidth>
        <Label>
          MVP <span className="text-muted">(optional)</span>
        </Label>
        <Select.Trigger className="h-12">
          <Select.Value />
          <Select.Indicator />
        </Select.Trigger>
        <Select.Popover>
          <ListBox>
            <ListBox.Item id="none" textValue="No MVP">
              No MVP
              <ListBox.ItemIndicator />
            </ListBox.Item>
            {roster.map((player) => (
              <ListBox.Item key={player.id} id={player.id} textValue={player.name}>
                {player.name}
                <ListBox.ItemIndicator />
              </ListBox.Item>
            ))}
          </ListBox>
        </Select.Popover>
      </Select>

      <div role="group" aria-labelledby={`keys-${match.id}`} className="flex flex-col gap-2">
        <span id={`keys-${match.id}`} className="text-sm text-muted">
          Key players <span className="text-muted/80">(up to 2)</span>
        </span>
        <div className="flex flex-wrap gap-1.5">
          {roster.map((player) => {
            const on = keys.includes(player.id);
            return (
              <ToggleButton
                key={player.id}
                size="sm"
                isSelected={on}
                isDisabled={player.id === mvp}
                onChange={(next) => toggleKey(player.id, next)}
                className={`h-11 rounded-full border px-3 text-sm ${
                  on ? "border-accent bg-accent-soft font-semibold text-accent-soft-foreground" : "border-border bg-transparent font-medium"
                }`}
              >
                {player.name}
              </ToggleButton>
            );
          })}
        </div>
      </div>

      {error ? (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{error}</Alert.Title>
          </Alert.Content>
        </Alert>
      ) : null}

      <Button
        type="submit"
        size="lg"
        fullWidth
        isDisabled={!ready}
        isPending={report.isPending}
        className="h-14 rounded-2xl text-base font-bold"
      >
        {({ isPending }) => (
          <>
            {isPending ? <Spinner color="current" size="sm" /> : null}
            {isPending ? "Sending…" : "Submit"}
          </>
        )}
      </Button>
    </Form>
  );
}
