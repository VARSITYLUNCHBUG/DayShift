import { Button, Chip, SearchField } from "@heroui/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { JsonBlock } from "../../components/JsonBlock";
import { Toggle } from "../../components/Toggle";
import type { EventLog } from "../../hooks/useEventLog";

const KIND_CLASS: Record<string, string> = { rest: "text-accent", gateway: "text-warning", control: "text-success" };

/** The simulator's live log: every REST call, gateway event and control call. */
export function EventLogPanel({ log }: { log: EventLog }) {
  const [filter, setFilter] = useState("");
  const [follow, setFollow] = useState(true);
  const [open, setOpen] = useState<number | null>(null);
  const bottom = useRef<HTMLLIElement>(null);
  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return q ? log.events.filter((e) => `${e.kind} ${e.summary}`.toLowerCase().includes(q)) : log.events;
  }, [log.events, filter]);
  const lastSeq = shown[shown.length - 1]?.seq;

  useEffect(() => {
    if (follow) bottom.current?.scrollIntoView({ block: "end" });
  }, [lastSeq, follow]);

  const color = log.status === "open" ? "success" : log.status === "connecting" ? "warning" : "danger";
  return (
    <section className="flex min-h-0 flex-col gap-2 rounded-lg bg-surface p-2" aria-labelledby="events-title">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="events-title" className="font-semibold">Events</h2>
        <Chip size="sm" variant="soft" color={color} aria-label={`event stream ${log.status}`}>{log.status}</Chip>
        <span className="text-xs text-muted">{log.events.length}</span>
        <Button size="sm" variant="ghost" className="ml-auto" onPress={log.clear}>Clear</Button>
      </div>
      <div className="flex items-center gap-2">
        <SearchField variant="secondary" aria-label="Filter events" value={filter} onChange={setFilter} className="flex-1">
          <SearchField.Group>
            <SearchField.SearchIcon />
            <SearchField.Input placeholder="Filter: POST, MESSAGE_CREATE…" />
            <SearchField.ClearButton />
          </SearchField.Group>
        </SearchField>
        <Toggle label="Follow" isSelected={follow} onChange={setFollow} />
      </div>
      <ul className="mono min-h-0 flex-1 overflow-auto" aria-label="Simulator events">
        {shown.map((e) => (
          <li key={e.seq}>
            <button
              type="button"
              aria-expanded={open === e.seq}
              className="flex w-full gap-2 rounded-sm px-1 text-left outline-none hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-focus"
              onClick={() => { setOpen(open === e.seq ? null : e.seq); }}
            >
              <span className={KIND_CLASS[e.kind] ?? "text-muted"}>{e.kind}</span>
              <span className={`truncate ${e.status !== null && e.status >= 400 ? "text-danger" : ""}`}>{e.summary}</span>
            </button>
            {open === e.seq ? <JsonBlock value={e.raw} className="my-1" /> : null}
          </li>
        ))}
        {shown.length === 0 ? <li className="text-muted">No events yet.</li> : null}
        <li ref={bottom} aria-hidden />
      </ul>
    </section>
  );
}
