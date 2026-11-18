import { Input, Label, TextArea, TextField } from "@heroui/react";

interface FieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "number";
  placeholder?: string;
  className?: string;
  onEnter?: () => void;
  autoFocus?: boolean;
}

/** Label + input in one line of JSX. */
export function Field({ label, value, onChange, type = "text", placeholder, className, onEnter, autoFocus }: FieldProps) {
  return (
    <TextField className={className} value={value} onChange={onChange} type={type} autoFocus={autoFocus}>
      <Label>{label}</Label>
      <Input
        variant="secondary"
        placeholder={placeholder}
        onKeyDown={(e) => {
          if (e.key === "Enter" && onEnter) onEnter();
        }}
      />
    </TextField>
  );
}

interface AreaProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
  className?: string;
}

export function AreaField({ label, value, onChange, rows = 6, placeholder, className }: AreaProps) {
  return (
    <TextField className={className} value={value} onChange={onChange}>
      <Label>{label}</Label>
      <TextArea variant="secondary" rows={rows} placeholder={placeholder} className="mono" spellCheck={false} />
    </TextField>
  );
}
