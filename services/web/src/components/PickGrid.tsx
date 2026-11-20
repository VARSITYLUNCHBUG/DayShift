import type { ReactNode } from "react";
import { ListBox, ListBoxItem } from "react-aria-components/ListBox";

import { cn } from "../lib/cn";

export interface PickState {
  isSelected: boolean;
  isDisabled: boolean;
  isFocusVisible: boolean;
}

interface Props<T> {
  items: readonly T[];
  getKey: (item: T) => string;
  /** What a screen reader hears for the item: "Ivy, Pike wants her". */
  getLabel: (item: T) => string;
  renderItem: (item: T, state: PickState) => ReactNode;
  /** The grid's name: "Heroes", "Players left". */
  "aria-label": string;
  selectedKey?: string | null;
  /** Leave out to show the grid read-only (waiting, watching): it stays browsable. */
  onSelect?: (key: string) => void;
  /** Taken or banned: never selectable (the arrows skip them; the label says why). */
  disabledKeys?: Iterable<string>;
  /** Grid columns, as Tailwind classes. */
  columns?: string;
  className?: string;
}

/** A pick grid: one Tab stop, the arrows move in two dimensions, Home and End jump, Enter or Space
 * selects, Tab leaves (F07's roving tabindex). React Aria's ListBox in its grid layout. */
export function PickGrid<T>({
  items,
  getKey,
  getLabel,
  renderItem,
  selectedKey = null,
  onSelect,
  disabledKeys,
  columns = "grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6",
  className,
  ...aria
}: Props<T>) {
  const readOnly = !onSelect;
  return (
    <ListBox
      aria-label={aria["aria-label"]}
      layout="grid"
      items={items.map((item) => ({ id: getKey(item), item }))}
      selectionMode={readOnly ? "none" : "single"}
      selectedKeys={selectedKey ? [selectedKey] : []}
      onSelectionChange={(keys) => {
        if (!onSelect || keys === "all") return;
        const [first] = [...keys];
        if (first !== undefined) onSelect(String(first));
      }}
      disabledKeys={disabledKeys}
      className={cn("grid gap-3 outline-none", columns, className)}
    >
      {({ id, item }) => (
        <ListBoxItem
          id={id}
          textValue={getLabel(item)}
          aria-label={getLabel(item)}
          className="cursor-pointer rounded-card outline-none data-disabled:cursor-default"
        >
          {({ isSelected, isDisabled, isFocusVisible }) => renderItem(item, { isSelected, isDisabled, isFocusVisible })}
        </ListBoxItem>
      )}
    </ListBox>
  );
}
