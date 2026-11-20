// Small text helpers shared by components and screens.

/** "Rook" → "RO", "Grey Talon" → "GT", "Mo & Krill" → "MK". */
export function initials(name: string): string {
  const words = name.replace(/&/g, " ").split(/\s+/).filter(Boolean);
  const first = words[0] ?? "";
  const last = words.at(-1) ?? "";
  if (words.length > 1) return (first.charAt(0) + last.charAt(0)).toUpperCase();
  return first.slice(0, 2).toUpperCase() || "?";
}

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

/** Sorts names the way people read them: P2 before P10. */
export function byName<T extends { name: string }>(a: T, b: T): number {
  return collator.compare(a.name, b.name);
}

/** "1,402" */
export function number(value: number): string {
  return value.toLocaleString("en-GB");
}

/** "1 sub", "2 subs" */
export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** "Rook" + "'s Team" when the server has no team name yet. */
export function teamName(names: { A: string | null; B: string | null }, team: "A" | "B"): string {
  return names[team] ?? (team === "A" ? "Team A" : "Team B");
}

/** "14:20", in the viewer's own time zone. */
export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** A rating change: "+31", "−26" (a real minus sign), "±0". */
export function signed(delta: number): string {
  if (delta > 0) return `+${number(delta)}`;
  if (delta < 0) return `−${number(-delta)}`;
  return "±0";
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** "12 Nov", in the viewer's own calendar. */
export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** How long ago, for lists: "Now", "24 min", "3 h", "Yesterday", "12 Nov". */
export function ago(iso: string, nowMs: number): string {
  const then = new Date(iso);
  const ms = nowMs - then.getTime();
  if (ms < MINUTE) return "Now";
  if (ms < HOUR) return `${Math.floor(ms / MINUTE)} min`;
  const now = new Date(nowMs);
  if (sameDay(then, now)) return `${Math.floor(ms / HOUR)} h`;
  const yesterday = new Date(nowMs - 24 * HOUR);
  if (sameDay(then, yesterday)) return "Yesterday";
  return shortDate(iso);
}

/** When something happened, to the minute: "Today 18:40", "Yesterday 18:40", "12 Nov 18:40". */
export function dayAndTime(iso: string, nowMs: number): string {
  const then = new Date(iso);
  const now = new Date(nowMs);
  const day = sameDay(then, now)
    ? "Today"
    : sameDay(then, new Date(nowMs - 24 * HOUR))
      ? "Yesterday"
      : shortDate(iso);
  return `${day} ${clockTime(iso)}`;
}

/** A share: 0.37 → "37%". */
export function percent(share: number): string {
  return `${Math.round(share * 100)}%`;
}

/** Wins out of games: "59%", or "–" before any. */
export function winRate(wins: number, games: number): string {
  return games > 0 ? percent(wins / games) : "–";
}

/** "27–19" with an en dash. */
export function record(wins: number, losses: number): string {
  return `${wins}–${losses}`;
}
