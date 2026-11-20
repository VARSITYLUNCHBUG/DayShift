import type { ReactNode } from "react";

import { cn } from "../lib/cn";
import { TEAM_CLASS } from "./team";

const VALUE_TONE = {
  text: "text-foreground",
  ok: "text-ok",
  danger: "text-danger",
  hk: TEAM_CLASS.hk.text,
  am: TEAM_CLASS.am.text,
} as const;

interface StatTileProps {
  label: ReactNode;
  value: ReactNode;
  line?: ReactNode;
  tone?: keyof typeof VALUE_TONE;
  className?: string;
}

/** One number with its label: "Your rating 1,512 +17". */
export function StatTile({ label, value, line, tone = "text", className }: StatTileProps) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1 rounded-card border border-line bg-surface px-4 py-3.5", className)}>
      <span className="text-micro font-bold text-muted">{label}</span>
      <span className={cn("font-display text-stat tabular-nums", VALUE_TONE[tone])}>{value}</span>
      {line ? <span className="text-micro font-semibold text-muted">{line}</span> : null}
    </div>
  );
}

/** A score line: "Kills 41 – 27", amber left, blue right. */
export function ScoreLine({ label, hk, am }: { label: ReactNode; hk: ReactNode; am: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-caption font-bold text-muted">{label}</span>
      <span className="font-display text-score tabular-nums">
        <span className="text-team-hk">{hk}</span>
        <span className="text-faint"> – </span>
        <span className="text-team-am">{am}</span>
      </span>
    </div>
  );
}

export interface Column<Row> {
  key: string;
  header: ReactNode;
  cell: (row: Row) => ReactNode;
  align?: "left" | "right";
  /** The row's name column: a row header for screen readers, kept in view on phones. */
  isRowHeader?: boolean;
}

interface TableProps<Row> {
  columns: readonly Column<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  /** Read by screen readers only: what the table is. */
  caption: string;
  /** The row to tint (yours). */
  highlight?: (row: Row) => boolean;
  className?: string;
}

/** A real <table> in a 20px panel. On narrow screens it scrolls sideways inside its box; the page
 * itself never does (P08). */
export function DataTable<Row>({ columns, rows, rowKey, caption, highlight, className }: TableProps<Row>) {
  return (
    <div className={cn("overflow-x-auto rounded-panel border border-line bg-surface", className)}>
      <table className="w-full border-collapse text-label font-semibold">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(
                  "border-b border-line px-3 py-2.5 text-micro font-extrabold whitespace-nowrap text-faint",
                  column.align === "right" ? "text-right" : "text-left",
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className={cn(highlight?.(row) && "bg-raised")}>
              {columns.map((column) => {
                const Cell = column.isRowHeader ? "th" : "td";
                return (
                  <Cell
                    key={column.key}
                    {...(column.isRowHeader ? { scope: "row" } : {})}
                    className={cn(
                      "border-b border-line px-3 py-2.5 tabular-nums",
                      column.align === "right" ? "text-right" : "text-left",
                      column.isRowHeader && "font-bold",
                    )}
                  >
                    {column.cell(row)}
                  </Cell>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const BAR_TONE = {
  text: "bg-foreground",
  hk: "bg-team-hk",
  am: "bg-team-am",
  muted: "bg-muted",
} as const;

/** A horizontal bar for a value out of a maximum. Decorative: the number is always in the text. */
export function Bar({ value, max, tone = "text", thick = false }: { value: number; max: number; tone?: keyof typeof BAR_TONE; thick?: boolean }) {
  const percent = max <= 0 ? 0 : Math.max(2, Math.min(100, (value / max) * 100));
  return (
    <span aria-hidden="true" className={cn("block rounded-full bg-background", thick ? "h-4.5" : "h-2.5")}>
      <span className={cn("block h-full rounded-full", BAR_TONE[tone])} style={{ width: `${percent.toFixed(1)}%` }} />
    </span>
  );
}

/** Shares side by side in one bar: [{ share: 0.52, tone: "hk" }, { share: 0.48, tone: "am" }]. */
export function StackedBar({ parts }: { parts: readonly { share: number; tone: keyof typeof BAR_TONE }[] }) {
  return (
    <div aria-hidden="true" className="flex h-4.5 overflow-hidden rounded-full bg-background">
      {parts.map((part, index) => (
        <span key={index} className={BAR_TONE[part.tone]} style={{ width: `${(part.share * 100).toFixed(1)}%` }} />
      ))}
    </div>
  );
}
