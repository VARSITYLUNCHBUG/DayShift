import { Label, ListBox, Select, type Key } from "@heroui/react";

export interface Option {
  id: string;
  label: string;
}

interface Props {
  label?: string;
  ariaLabel?: string;
  options: Option[];
  value: string | null;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  isDisabled?: boolean;
}

/** A single-choice HeroUI Select over plain string options. */
export function SimpleSelect({ label, ariaLabel, options, value, onChange, placeholder, className, isDisabled }: Props) {
  return (
    <Select
      variant="secondary"
      aria-label={label ? undefined : ariaLabel}
      className={className}
      placeholder={placeholder ?? "Choose…"}
      value={value}
      isDisabled={isDisabled}
      onChange={(key: Key | Key[] | null) => {
        if (key !== null && !Array.isArray(key)) onChange(String(key));
      }}
    >
      {label ? <Label>{label}</Label> : null}
      <Select.Trigger>
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <ListBox>
          {options.map((o) => (
            <ListBox.Item key={o.id} id={o.id} textValue={o.label}>
              {o.label}
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}
