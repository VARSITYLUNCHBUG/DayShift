import { Button, Chip, Disclosure, Dropdown, Input, Label, toast } from "@heroui/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { sim, type SimComponent, type SimInteraction, type SimMessage, type SimModal } from "../../api";
import { JsonBlock } from "../../components/JsonBlock";
import { describeError, useAction } from "../../hooks/useAction";
import { usePoll } from "../../hooks/usePoll";
import { BotModal } from "./BotModal";
import type { Target } from "./ChannelList";

// Discord component types and button styles the view renders.
const BUTTON = 2;
const STRING_SELECT = 3;
const LINK_STYLE = 5;
const BUTTON_VARIANT: Record<number, "primary" | "secondary" | "tertiary" | "danger-soft"> = {
  1: "primary",
  2: "tertiary",
  3: "secondary",
  4: "danger-soft",
};

/** User, role and channel selects have no options: type the ids to send. */
function IdSelect({ component, canAct, onSubmit }: { component: SimComponent; canAct: boolean; onSubmit: (values: string[]) => void }) {
  const [value, setValue] = useState("");
  const label = component.label ?? "ids, comma separated";
  return (
    <span className="flex items-center gap-1">
      <Input
        variant="secondary"
        aria-label={label}
        className="mono w-56"
        placeholder={label}
        value={value}
        onChange={(e) => { setValue(e.target.value); }}
        disabled={component.disabled || !canAct}
      />
      <Button
        size="sm"
        variant="outline"
        isDisabled={component.disabled || !canAct || !value.trim()}
        onPress={() => { onSubmit(value.split(/[\s,]+/).filter(Boolean)); }}
      >
        Select
      </Button>
    </span>
  );
}

function ComponentControl({ component, canAct, onClick }: { component: SimComponent; canAct: boolean; onClick: (values?: string[]) => void }) {
  const text = `${component.emoji ? `${component.emoji} ` : ""}${component.label ?? component.customId ?? "?"}`;
  if (component.type === BUTTON) {
    if (component.style === LINK_STYLE || component.url) {
      return (
        <a className="text-link underline focus-visible:outline-2 focus-visible:outline-focus" href={component.url ?? "#"} target="_blank" rel="noreferrer">
          {text} <span aria-label="(opens in a new tab)">↗</span>
        </a>
      );
    }
    return (
      <Button
        size="sm"
        variant={BUTTON_VARIANT[component.style ?? 2] ?? "tertiary"}
        isDisabled={component.disabled || !canAct || !component.customId}
        onPress={() => { onClick(); }}
      >
        {text}
      </Button>
    );
  }
  if (component.type === STRING_SELECT) {
    return (
      <Dropdown>
        <Button size="sm" variant="outline" isDisabled={component.disabled || !canAct}>
          {component.label ?? "Select…"} ▾
        </Button>
        <Dropdown.Popover>
          <Dropdown.Menu aria-label={component.label ?? "Select"} onAction={(key) => { onClick([String(key)]); }}>
            {component.options.map((o) => (
              <Dropdown.Item key={o.value} id={o.value} textValue={o.label}>
                <Label>{o.label}</Label>
              </Dropdown.Item>
            ))}
          </Dropdown.Menu>
        </Dropdown.Popover>
      </Dropdown>
    );
  }
  return <IdSelect component={component} canAct={canAct} onSubmit={onClick} />;
}

function MessageRow({
  message,
  ephemeralName,
  canAct,
  onClick,
}: {
  message: SimMessage;
  ephemeralName: string | null;
  canAct: boolean;
  onClick: (message: SimMessage, component: SimComponent, values?: string[]) => void;
}) {
  const body = message.content || message.text;
  return (
    <article className="rounded-md border border-separator p-2" aria-label={`Message from ${message.authorName}`}>
      <header className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <span className="font-semibold text-foreground">{message.authorName}</span>
        {message.authorIsBot ? <Chip size="sm" color="accent" variant="soft">bot</Chip> : null}
        {message.createdAt ? <time dateTime={message.createdAt}>{new Date(message.createdAt).toLocaleTimeString()}</time> : null}
        {message.edited ? <span>(edited)</span> : null}
        {message.ephemeral ? <span>(ephemeral{ephemeralName ? `, only ${ephemeralName} sees it` : ""})</span> : null}
        {message.loading ? <span>(thinking…)</span> : null}
        <span className="mono ml-auto">{message.id}</span>
      </header>
      {body ? <p className="mt-1 whitespace-pre-wrap">{body}</p> : null}
      {message.content && message.text && message.text !== message.content ? (
        <p className="mt-1 whitespace-pre-wrap text-muted">{message.text}</p>
      ) : null}
      {message.embeds.map((text, i) => (
        <p key={i} className="mt-1 border-l-2 border-accent pl-2 text-muted">{text}</p>
      ))}
      {message.attachments.map((a, i) => (
        <div key={a.url ?? i} className="mt-1 text-xs">
          <span aria-hidden>📎 </span>
          {a.url ? (
            <a className="text-link underline" href={a.url} target="_blank" rel="noreferrer">{a.filename}</a>
          ) : (
            a.filename
          )}
        </div>
      ))}
      {message.components.length ? (
        <div className="mt-2 flex flex-wrap gap-1" role="group" aria-label="Buttons and selects">
          {message.components.map((c, i) => (
            <ComponentControl
              key={`${c.customId ?? "c"}-${i}`}
              component={c}
              canAct={canAct}
              onClick={(values) => { onClick(message, c, values); }}
            />
          ))}
        </div>
      ) : null}
      <Disclosure className="mt-1">
        <Disclosure.Heading>
          <Button slot="trigger" size="sm" variant="ghost" className="h-6 px-1 text-xs text-muted" aria-label={`Raw payload of message ${message.id}`}>
            raw
            <Disclosure.Indicator />
          </Button>
        </Disclosure.Heading>
        <Disclosure.Content>
          <Disclosure.Body>
            <JsonBlock value={message.raw} />
          </Disclosure.Body>
        </Disclosure.Content>
      </Disclosure>
    </article>
  );
}

/** Snowflakes order by length, then by digits (they don't fit in a JS number). */
function bySnowflake(a: { id: string }, b: { id: string }): number {
  if (a.id.length !== b.id.length) return a.id.length - b.id.length;
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
}

/** The toast after a click or a modal: what the bot said back, if anything. */
function replyText(label: string) {
  return (result: SimInteraction) =>
    result.modal ? `${label}: the bot opened “${result.modal.title}”` : result.replies.length ? `Bot: ${result.replies.join(" · ")}` : `${label}: done`;
}

interface OpenModal {
  userId: string;
  modal: SimModal;
}

/** One channel or DM: its messages with clickable components, and a box to chat as a user. */
export function Messages({
  target,
  actorId,
  nameOf,
  onChanged,
}: {
  target: Target;
  actorId: string | null;
  nameOf: ReadonlyMap<string, string>;
  onChanged: () => void;
}) {
  const load = useMemo(
    () =>
      target.kind === "channel"
        ? (signal: AbortSignal) => sim.channelMessages(target.id, 50, signal)
        : (signal: AbortSignal) => sim.userDms(target.id, 50, signal),
    [target.kind, target.id],
  );
  const messages = usePoll(load, 1500);
  const { run } = useAction(messages.refresh);
  const [draft, setDraft] = useState("");
  const [modal, setModal] = useState<OpenModal | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const sorted = useMemo(() => (messages.data ?? []).slice().sort(bySnowflake), [messages.data]);
  const lastId = sorted[sorted.length - 1]?.id;
  // In a DM only that user can click or type; in a channel, whoever you act as.
  const sender = target.kind === "dm" ? target.id : actorId;

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [lastId]);

  const click = (message: SimMessage, component: SimComponent, values?: string[]) => {
    const customId = component.customId;
    // An ephemeral message can only be clicked by the user it was shown to.
    const user = message.ephemeralFor ?? sender;
    if (!user || !customId) return;
    const label = `Click ${component.label ?? customId}`;
    void run(
      label,
      () => sim.clickComponent({ user_id: user, message_id: message.id, custom_id: customId, ...(values ? { values } : {}) }),
      replyText(label),
    ).then((result) => {
      if (result?.modal) setModal({ userId: user, modal: result.modal });
      onChanged();
    });
  };

  const send = () => {
    const content = draft.trim();
    if (!sender || !content) return;
    setDraft("");
    const where = target.kind === "dm" ? { dm: true as const } : { channel_id: target.id };
    void run("Send message", () => sim.sendMessage(sender, where, content), "Message sent");
  };

  const title = target.kind === "channel" ? `# ${target.name}` : `DMs of ${target.name}`;
  return (
    <section className="flex min-h-0 flex-col gap-2 rounded-lg bg-surface p-2" aria-labelledby="messages-title">
      <div className="flex items-center gap-2 px-1">
        <h2 id="messages-title" className="font-semibold">{title}</h2>
        <span className="mono text-xs text-muted">{target.id}</span>
        {messages.error ? <span role="alert" className="text-danger">{describeError(messages.error)}</span> : null}
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-auto px-1" role="log" aria-label={`Messages in ${title}`}>
        {sorted.map((m) => (
          <MessageRow
            key={m.id}
            message={m}
            ephemeralName={m.ephemeralFor ? (nameOf.get(m.ephemeralFor) ?? m.ephemeralFor) : null}
            canAct={(m.ephemeralFor ?? sender) !== null}
            onClick={click}
          />
        ))}
        {messages.data && sorted.length === 0 ? <p className="text-muted">No messages.</p> : null}
        <div ref={bottom} />
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <Input
          variant="secondary"
          aria-label={sender ? `Message as ${nameOf.get(sender) ?? sender}` : "Message (pick a user to act as first)"}
          className="flex-1"
          placeholder={sender ? "Type as the acting user, Enter to send" : "Pick a user to act as"}
          value={draft}
          disabled={!sender}
          onChange={(e) => { setDraft(e.target.value); }}
        />
        <Button size="sm" type="submit" isDisabled={!sender || !draft.trim()}>
          Send
        </Button>
      </form>
      {modal ? (
        <BotModal
          key={`${modal.userId}:${modal.modal.customId}`}
          userId={modal.userId}
          userName={nameOf.get(modal.userId) ?? modal.userId}
          modal={modal.modal}
          onClose={() => { setModal(null); }}
          onSubmitted={(result) => {
            toast.success(replyText(modal.modal.title)(result), { timeout: 4000 });
            messages.refresh();
            onChanged();
          }}
        />
      ) : null}
    </section>
  );
}
