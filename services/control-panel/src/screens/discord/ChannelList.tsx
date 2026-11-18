import type { SimState } from "../../api";

export interface Target {
  kind: "channel" | "dm";
  id: string;
  name: string;
}

// Discord channel types the list cares about.
const CATEGORY = 4;
const VOICE_TYPES = new Set([2, 13]);

const itemClass = (active: boolean) =>
  `flex w-full items-center gap-1 truncate rounded-sm px-2 py-0.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-focus ${
    active ? "bg-accent-soft text-accent-soft-foreground" : "hover:bg-surface-hover"
  }`;

/** The guild's channels by category, voice channels with who is in them, then every DM. */
export function ChannelList({
  state,
  target,
  onSelect,
}: {
  state: SimState;
  target: Target | null;
  onSelect: (t: Target) => void;
}) {
  const nameOf = new Map(state.members.map((m) => [m.id, m.name]));
  const categories = state.channels.filter((c) => c.type === CATEGORY).sort((a, b) => a.position - b.position);
  const inGroup = (parent: string | null) =>
    state.channels.filter((c) => c.type !== CATEGORY && c.parentId === parent).sort((a, b) => a.position - b.position);
  const groups = [{ id: null, name: "No category" }, ...categories.map((c) => ({ id: c.id, name: c.name }))];
  const humans = state.members.filter((m) => !m.isBot);

  const item = (t: Target, label: string, extra?: string) => {
    const active = target?.kind === t.kind && target.id === t.id;
    return (
      <li key={`${t.kind}-${t.id}`}>
        <button
          type="button"
          aria-current={active ? "page" : undefined}
          onClick={() => { onSelect(t); }}
          className={itemClass(active)}
        >
          <span className="truncate">{label}</span>
          {extra ? <span className="ml-auto text-xs text-muted">{extra}</span> : null}
        </button>
      </li>
    );
  };

  return (
    <nav className="flex min-h-0 flex-col gap-3 overflow-auto rounded-lg bg-surface p-2" aria-label="Channels and DMs">
      <div className="px-2 text-xs text-muted">
        {state.guildName ?? "guild"} <span className="mono">{state.guildId}</span>
      </div>
      {groups.map((g) => {
        const channels = inGroup(g.id);
        if (channels.length === 0) return null;
        const headingId = `channels-${g.id ?? "none"}`;
        return (
          <section key={g.id ?? "none"} aria-labelledby={headingId}>
            <h3 id={headingId} className="px-2 text-xs font-semibold uppercase text-muted">{g.name}</h3>
            <ul>
              {channels.map((c) =>
                VOICE_TYPES.has(c.type) ? (
                  <li key={c.id} className="px-2 py-0.5 text-muted">
                    <span aria-label={`voice channel ${c.name}`}>🔊 {c.name}</span>
                    {c.voiceMembers.length ? (
                      <ul className="pl-4 text-xs">
                        {c.voiceMembers.map((id) => <li key={id}>{nameOf.get(id) ?? id}</li>)}
                      </ul>
                    ) : null}
                  </li>
                ) : (
                  item({ kind: "channel", id: c.id, name: c.name }, `# ${c.name}`)
                ),
              )}
            </ul>
          </section>
        );
      })}
      <section aria-labelledby="channels-dms">
        <h3 id="channels-dms" className="px-2 text-xs font-semibold uppercase text-muted">Direct messages</h3>
        <ul>
          {humans.map((m) => item({ kind: "dm", id: m.id, name: m.name }, `@ ${m.name}`, m.dmOpen ? undefined : "DMs off"))}
          {humans.length === 0 ? <li className="px-2 text-muted">No fake users.</li> : null}
        </ul>
      </section>
    </nav>
  );
}
