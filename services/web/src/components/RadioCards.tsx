import type { ReactNode } from "react";
import { Label } from "react-aria-components/Label";
import { RadioButton, RadioField, RadioGroup } from "react-aria-components/RadioGroup";

import { cn } from "../lib/cn";
import type { TeamKey } from "./team";
import { TEAM_CLASS } from "./team";

export interface RadioCard {
  id: string;
  title: ReactNode;
  /** The line under the title: "The game is on: subbing yourself out counts as leaving". */
  line?: ReactNode;
  /** Colours the chosen card's edge (a team's player); cream by default. */
  tone?: TeamKey | null;
  isDisabled?: boolean;
}

interface Props {
  /** The question: "Who needs to come out?". */
  label: ReactNode;
  options: readonly RadioCard[];
  value: string | null;
  onChange: (id: string) => void;
  /** Lay the cards out in columns rather than one under another. */
  columns?: string;
  className?: string;
}

/** One choice from a few, as cards with a radio dot (C03): arrow keys move, the group is one Tab
 * stop. React Aria's RadioGroup, so it reads as radios. */
export function RadioCards({ label, options, value, onChange, columns, className }: Props) {
  return (
    <RadioGroup value={value} onChange={onChange} className={cn("flex flex-col gap-2", className)}>
      <Label className="text-label font-extrabold text-foreground">{label}</Label>
      <div className={cn("grid gap-2", columns ?? "grid-cols-1")}>
        {options.map((option) => (
          <RadioField key={option.id} value={option.id} isDisabled={option.isDisabled}>
            <RadioButton
              className={({ isSelected, isDisabled }) =>
                cn(
                  "flex min-h-14 cursor-pointer items-center gap-3.5 rounded-card border-2 bg-surface px-4 py-3 outline-none transition-state",
                  isSelected ? (option.tone ? TEAM_CLASS[option.tone].border : "border-foreground") : "border-line",
                  isSelected && "bg-raised",
                  isDisabled && "cursor-not-allowed opacity-60",
                )
              }
            >
              {({ isSelected }) => (
                <>
                  <span
                    aria-hidden="true"
                    className={cn(
                      "flex size-5 shrink-0 items-center justify-center rounded-full border-2",
                      isSelected ? "border-foreground" : "border-line-strong",
                    )}
                  >
                    {isSelected ? <span className="size-2.5 rounded-full bg-foreground" /> : null}
                  </span>
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-body font-extrabold">{option.title}</span>
                    {option.line ? <span className="text-caption text-muted">{option.line}</span> : null}
                  </span>
                </>
              )}
            </RadioButton>
          </RadioField>
        ))}
      </div>
    </RadioGroup>
  );
}
