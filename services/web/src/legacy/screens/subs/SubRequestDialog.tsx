import { Alert, Button, Chip, Label, ListBox, Modal, Select, Spinner, ToggleButton } from "@heroui/react";
import type { Key } from "@heroui/react";
import { useEffect, useState } from "react";

import { errorText } from "../../components/toast";
import { plural } from "../../lib/format";
import { useAction, useConnectionState } from "../../../live/hooks";
import type { MatchSnap, SubOutOptions, SubRequested } from "../../../live/types";
import { otherCaptainName } from "./subs";

interface Props {
  match: MatchSnap;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  /** The request went in: its id, and whether the player asked for themself. */
  onRequested?: (requestId: string, isSelf: boolean) => void;
}

/** 4.1 Request a sub: yourself, or (captains) a teammate, which the other captain approves. */
export function SubRequestDialog({ match, isOpen, onOpenChange, onRequested }: Props) {
  return (
    <Modal.Backdrop isOpen={isOpen} onOpenChange={onOpenChange}>
      <Modal.Container size="sm" scroll="inside">
        <Modal.Dialog>
          {({ close }) => (
            <>
              <Modal.CloseTrigger aria-label="Close" />
              <Modal.Header>
                <Modal.Heading className="text-2xl font-bold">Request a sub</Modal.Heading>
              </Modal.Header>
              <Modal.Body>
                <RequestForm match={match} onDone={close} onRequested={onRequested} />
              </Modal.Body>
            </>
          )}
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}

const CARD = "flex h-auto min-h-18 w-full flex-col items-start gap-2 rounded-2xl border-2 p-4 text-left whitespace-normal";

function RequestForm({
  match,
  onDone,
  onRequested,
}: {
  match: MatchSnap;
  onDone: () => void;
  onRequested?: (requestId: string, isSelf: boolean) => void;
}) {
  const { run: ask } = useAction();
  const request = useAction();
  const [options, setOptions] = useState<SubOutOptions | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [who, setWho] = useState<"self" | "teammate" | null>(null);
  const [teammate, setTeammate] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Who this player may sub out is the server's call: ask it each time the dialog opens, once
  // the connection is up.
  const connected = useConnectionState() === "open";
  const asked = options !== null || loadError !== null;
  useEffect(() => {
    if (!connected || asked) return;
    let current = true;
    ask("subs.options", { match_id: match.id }).then(
      (ack) => {
        if (!current) return;
        const result = ack.result as SubOutOptions;
        setOptions(result);
        setWho(result.choices.some((c) => c.is_self) ? "self" : "teammate");
      },
      (reason: unknown) => {
        if (current) setLoadError(errorText(reason));
      },
    );
    return () => {
      current = false;
    };
  }, [ask, match.id, connected, asked]);

  if (loadError) {
    return (
      <Alert status="danger">
        <Alert.Indicator />
        <Alert.Content>
          <Alert.Title>{loadError}</Alert.Title>
        </Alert.Content>
      </Alert>
    );
  }
  if (!options) {
    return (
      <div className="flex justify-center py-10">
        <Spinner aria-label="Loading" />
      </div>
    );
  }

  const self = options.choices.find((c) => c.is_self) ?? null;
  const teammates = options.choices.filter((c) => !c.is_self);
  const approver = otherCaptainName(match, match.viewer.team);
  const leaving = who === "self" ? self?.player_id : who === "teammate" ? teammate : null;
  const cost = options.game_on ? "Leaving a game" : options.dodge ? "Dodge" : null;

  const send = () => {
    if (!leaving) return;
    setError(null);
    request.run("subs.request", { match_id: match.id, player_id: leaving }).then(
      (ack) => {
        onDone();
        const result = ack.result as SubRequested | undefined;
        if (result) onRequested?.(result.request_id, who === "self");
      },
      (reason: unknown) => setError(errorText(reason)),
    );
  };

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted">The match pauses until a sub takes the spot.</p>
      {self ? (
        <ToggleButton
          isSelected={who === "self"}
          onChange={() => setWho("self")}
          className={`${CARD} ${who === "self" ? "border-accent bg-accent-soft" : "border-border bg-background"}`}
        >
          <span className="text-base font-semibold">Sub me out</span>
          {cost ? (
            <Chip color="danger" variant="soft" size="sm" className="font-semibold">
              {options.strikes > 0 ? `${cost} · +${plural(options.strikes, "strike")}` : cost}
            </Chip>
          ) : null}
        </ToggleButton>
      ) : null}
      <ToggleButton
        isSelected={who === "teammate"}
        isDisabled={teammates.length === 0}
        onChange={() => setWho("teammate")}
        className={`${CARD} ${who === "teammate" ? "border-accent bg-accent-soft" : "border-border bg-background"}`}
      >
        <span className="text-base font-semibold">Sub out a teammate</span>
        <span className="text-sm text-muted">Captains only{approver ? ` · ${approver} approves` : ""}</span>
      </ToggleButton>
      {teammates.length > 0 ? (
        <Select
          placeholder="Choose a player"
          value={teammate}
          onChange={(key: Key | Key[] | null) => setTeammate(key === null ? null : String(key))}
          isDisabled={who !== "teammate"}
          variant="secondary"
          fullWidth
        >
          <Label>Teammate</Label>
          <Select.Trigger className="h-12">
            <Select.Value />
            <Select.Indicator />
          </Select.Trigger>
          <Select.Popover>
            <ListBox>
              {teammates.map((choice) => (
                <ListBox.Item key={choice.player_id} id={choice.player_id} textValue={choice.name}>
                  {choice.name}
                  <ListBox.ItemIndicator />
                </ListBox.Item>
              ))}
            </ListBox>
          </Select.Popover>
        </Select>
      ) : null}
      {error ? (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{error}</Alert.Title>
          </Alert.Content>
        </Alert>
      ) : null}
      <Button
        size="lg"
        fullWidth
        isDisabled={!leaving}
        isPending={request.pending}
        onPress={send}
        className="h-13 rounded-2xl text-base font-bold"
      >
        {({ isPending }) => (
          <>
            {isPending ? <Spinner color="current" size="sm" /> : null}
            Request
          </>
        )}
      </Button>
    </div>
  );
}
