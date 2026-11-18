import {
  Button,
  Description,
  Input,
  Label,
  ListBox,
  Modal,
  Select,
  Spinner,
  TextArea,
  TextField,
  type Key,
} from "@heroui/react";
import { useId, useState } from "react";

import { sim, type ModalField, type ModalSubmit, type SimInteraction, type SimModal } from "../../api";
import { describeError } from "../../hooks/useAction";

type Answers = Record<string, string | string[]>;
type Files = Record<string, File[]>;

function initialAnswers(fields: ModalField[]): Answers {
  const answers: Answers = {};
  for (const f of fields) {
    if (f.kind === "text") answers[f.customId] = f.value;
    else if (f.kind === "select") answers[f.customId] = [];
  }
  return answers;
}

/** A select inside a modal: string options from a list, user/role/channel ids typed in. */
function SelectField({
  field,
  value,
  onChange,
}: {
  field: Extract<ModalField, { kind: "select" }>;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  if (field.options.length === 0) {
    return (
      <TextField value={value.join(", ")} onChange={(text) => { onChange(text.split(/[\s,]+/).filter(Boolean)); }} isRequired={field.required}>
        <Label>{field.label}</Label>
        <Input variant="secondary" className="mono" placeholder={field.placeholder ?? "ids or names, comma separated"} />
        {field.description ? <Description>{field.description}</Description> : null}
      </TextField>
    );
  }
  const multiple = field.maxValues > 1;
  return (
    <Select
      variant="secondary"
      selectionMode={multiple ? "multiple" : "single"}
      placeholder={field.placeholder ?? "Choose…"}
      isRequired={field.required}
      value={multiple ? value : (value[0] ?? null)}
      onChange={(key: Key | Key[] | null) => {
        onChange(key === null ? [] : Array.isArray(key) ? key.map(String) : [String(key)]);
      }}
    >
      <Label>{field.label}</Label>
      <Select.Trigger>
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      {field.description ? <Description>{field.description}</Description> : null}
      <Select.Popover>
        <ListBox>
          {field.options.map((o) => (
            <ListBox.Item key={o.value} id={o.value} textValue={o.label}>
              {o.label}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}

/** A file upload: pick real files, or leave it empty to send the sim's placeholder image. */
function FileField({
  field,
  files,
  onChange,
}: {
  field: Extract<ModalField, { kind: "file" }>;
  files: File[];
  onChange: (files: File[]) => void;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {field.label}
        {field.required ? <span className="text-danger" aria-hidden> *</span> : null}
      </label>
      <input
        id={id}
        type="file"
        accept="image/*"
        multiple={field.maxValues > 1}
        aria-describedby={`${id}-hint`}
        className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-default file:px-3 file:py-1 file:text-default-foreground focus-visible:outline-2 focus-visible:outline-focus"
        onChange={(e) => { onChange(Array.from(e.target.files ?? []).slice(0, field.maxValues)); }}
      />
      <p id={`${id}-hint`} className="text-xs text-muted">
        {field.description ? `${field.description} ` : ""}
        {files.length
          ? `${files.length} file${files.length > 1 ? "s" : ""} chosen.`
          : "No file chosen: sends a 1x1 placeholder PNG."}
      </p>
    </div>
  );
}

/**
 * The form a button opened, as the fake user sees it in Discord. Submitting uploads any chosen
 * files to the simulator first, then sends the modal through `/_sim/interactions/modal`.
 */
export function BotModal({
  userId,
  userName,
  modal,
  onClose,
  onSubmitted,
}: {
  userId: string;
  userName: string;
  modal: SimModal;
  onClose: () => void;
  onSubmitted: (result: SimInteraction) => void;
}) {
  const [answers, setAnswers] = useState<Answers>(() => initialAnswers(modal.fields));
  const [files, setFiles] = useState<Files>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const attachments: ModalSubmit["attachments"] = {};
      for (const f of modal.fields) {
        if (f.kind !== "file") continue;
        const chosen = files[f.customId] ?? [];
        if (chosen.length) {
          const stored = await Promise.all(chosen.map((file) => sim.uploadAttachment(file, file.name)));
          attachments[f.customId] = stored.map((a) => a.id);
        } else if (f.required) {
          // A file spec without data: the simulator makes a 1x1 PNG.
          attachments[f.customId] = [{ filename: "screenshot.png" }];
        }
      }
      const result = await sim.submitModal({ user_id: userId, custom_id: modal.customId, values: answers, attachments });
      onSubmitted(result);
      onClose();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal.Backdrop isOpen onOpenChange={(open) => { if (!open) onClose(); }}>
      <Modal.Container size="md" scroll="inside">
        <Modal.Dialog>
          <Modal.CloseTrigger />
          <Modal.Header>
            <Modal.Heading>{modal.title}</Modal.Heading>
            <p className="text-xs text-muted">
              Opened by the bot for {userName}. <span className="mono">{modal.customId}</span>
            </p>
          </Modal.Header>
          <Modal.Body>
            <form
              id={`modal-${modal.customId}`}
              className="flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                void submit();
              }}
            >
              {modal.fields.map((f, i) => {
                if (f.kind === "note") return <p key={i} className="whitespace-pre-wrap text-muted">{f.text}</p>;
                if (f.kind === "file") {
                  return (
                    <FileField
                      key={f.customId}
                      field={f}
                      files={files[f.customId] ?? []}
                      onChange={(chosen) => { setFiles((prev) => ({ ...prev, [f.customId]: chosen })); }}
                    />
                  );
                }
                if (f.kind === "select") {
                  const value = answers[f.customId];
                  return (
                    <SelectField
                      key={f.customId}
                      field={f}
                      value={Array.isArray(value) ? value : []}
                      onChange={(v) => { setAnswers((prev) => ({ ...prev, [f.customId]: v })); }}
                    />
                  );
                }
                const value = answers[f.customId];
                return (
                  <TextField
                    key={f.customId}
                    value={typeof value === "string" ? value : ""}
                    onChange={(v) => { setAnswers((prev) => ({ ...prev, [f.customId]: v })); }}
                    isRequired={f.required}
                    autoFocus={i === 0}
                  >
                    <Label>{f.label}</Label>
                    {f.multiline ? (
                      <TextArea variant="secondary" rows={3} placeholder={f.placeholder ?? undefined} maxLength={f.maxLength ?? undefined} />
                    ) : (
                      <Input variant="secondary" placeholder={f.placeholder ?? undefined} maxLength={f.maxLength ?? undefined} />
                    )}
                    {f.description ? <Description>{f.description}</Description> : null}
                  </TextField>
                );
              })}
              {modal.fields.length === 0 ? <p className="text-muted">This modal has no fields.</p> : null}
              {error ? <p role="alert" className="text-danger">{error}</p> : null}
            </form>
          </Modal.Body>
          <Modal.Footer>
            <Button slot="close" variant="tertiary">Cancel</Button>
            <Button type="submit" form={`modal-${modal.customId}`} isPending={busy}>
              {({ isPending }) => (
                <>
                  {isPending ? <Spinner color="current" size="sm" /> : null}
                  Submit as {userName}
                </>
              )}
            </Button>
          </Modal.Footer>
        </Modal.Dialog>
      </Modal.Container>
    </Modal.Backdrop>
  );
}
