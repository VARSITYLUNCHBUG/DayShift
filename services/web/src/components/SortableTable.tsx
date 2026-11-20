import { useState } from "react";
import type { ReactNode } from "react";

import { cn } from "../lib/cn";

export interface SortColumn<Row> {
  key: string;
  header: string;
  cell: (row: Row) => ReactNode;
  /** The number (or text) the column sorts by; leave out for a column that doesn't sort. */
  sortValue?: (row: Row) => number | string;
  align?: "left" | "right";
  isRowHeader?: boolean;
}

interface Props<Row> {
  columns: readonly SortColumn<Row>[];
  rows: readonly Row[];
  rowKey: (row: Row) => string;
  caption: string;
  /** The column sorted first, biggest first. */
  initialSort?: string;
  highlight?: (row: Row) => boolean;
  /** A tint per row (a team's soft colour). */
  rowClass?: (row: Row) => string | undefined;
  className?: string;
}

type Direction = "ascending" | "descending";

/** Sorts rows by a column: numbers biggest first by default, text A to Z. */
export function sortRows<Row>(rows: readonly Row[], column: SortColumn<Row> | undefined, direction: Direction): Row[] {
  if (!column?.sortValue) return [...rows];
  const value = column.sortValue;
  const sign = direction === "ascending" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = value(a);
    const y = value(b);
    const order = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
    return order * sign;
  });
}

/** A real <table> whose headers sort it (aria-sort on the sorted one). Scrolls sideways inside its
 * own box on narrow screens, never the page. */
export function SortableTable<Row>({ columns, rows, rowKey, caption, initialSort, highlight, rowClass, className }: Props<Row>) {
  const [sort, setSort] = useState<{ key: string; direction: Direction } | null>(initialSort ? { key: initialSort, direction: "descending" } : null);
  const column = columns.find((c) => c.key === sort?.key);
  const sorted = sort ? sortRows(rows, column, sort.direction) : [...rows];
  return (
    <div className={cn("overflow-x-auto rounded-panel border border-line bg-surface", className)}>
      <table className="w-full border-collapse text-label font-semibold">
        <caption className="sr-only">{caption}. Sort by any column with its header.</caption>
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              const right = c.align === "right";
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={active ? sort.direction : undefined}
                  className={cn("border-b border-line px-2 py-1 text-micro font-extrabold whitespace-nowrap text-faint", right ? "text-right" : "text-left")}
                >
                  {c.sortValue ? (
                    <button
                      type="button"
                      onClick={() =>
                        setSort((old) => ({
                          key: c.key,
                          direction: old?.key === c.key && old.direction === "descending" ? "ascending" : old?.key === c.key ? "descending" : typeof c.sortValue?.(rows[0] as Row) === "string" ? "ascending" : "descending",
                        }))
                      }
                      className={cn("inline-flex min-h-11 items-center gap-1 rounded-small px-1.5", right && "flex-row-reverse", active ? "text-foreground" : "hover:text-foreground")}
                    >
                      {c.header}
                      <span aria-hidden="true" className={cn(!active && "opacity-0")}>
                        {active && sort.direction === "ascending" ? "▲" : "▼"}
                      </span>
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={rowKey(row)} className={cn(highlight?.(row) ? "bg-raised" : rowClass?.(row))}>
              {columns.map((c) => {
                const Cell = c.isRowHeader ? "th" : "td";
                return (
                  <Cell
                    key={c.key}
                    {...(c.isRowHeader ? { scope: "row" } : {})}
                    className={cn("border-b border-line px-3 py-2 whitespace-nowrap tabular-nums", c.align === "right" ? "text-right" : "text-left", c.isRowHeader && "font-normal")}
                  >
                    {c.cell(row)}
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
