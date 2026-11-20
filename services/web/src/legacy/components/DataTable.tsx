import { Table } from "@heroui/react";
import type { ReactNode } from "react";

export interface Column<T> {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  align?: "start" | "end";
  /** One column names the row for screen readers: usually the player or match. */
  isRowHeader?: boolean;
}

interface Props<T> {
  label: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  /** Extra classes for a row: the viewer's own, highlighted. */
  rowClassName?: (row: T) => string | undefined;
  empty?: ReactNode;
}

/** A read-only table on HeroUI's Table: leaderboards, match lists, results. */
export function DataTable<T>({ label, columns, rows, rowKey, rowClassName, empty = "Nothing here yet" }: Props<T>) {
  const align = (column: Column<T>) => (column.align === "end" ? "text-right" : "text-left");
  return (
    <Table className="overflow-hidden rounded-2xl border border-border">
      <Table.ScrollContainer>
        <Table.Content aria-label={label} className="min-w-140 tabular-nums">
          <Table.Header>
            {columns.map((column) => (
              <Table.Column key={column.id} id={column.id} isRowHeader={column.isRowHeader} className={align(column)}>
                {column.header}
              </Table.Column>
            ))}
          </Table.Header>
          <Table.Body renderEmptyState={() => <span className="text-muted">{empty}</span>}>
            {rows.map((row) => (
              <Table.Row key={rowKey(row)} id={rowKey(row)} className={rowClassName?.(row)}>
                {columns.map((column) => (
                  <Table.Cell key={column.id} className={align(column)}>
                    {column.cell(row)}
                  </Table.Cell>
                ))}
              </Table.Row>
            ))}
          </Table.Body>
        </Table.Content>
      </Table.ScrollContainer>
    </Table>
  );
}
