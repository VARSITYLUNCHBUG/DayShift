import { Button } from "@heroui/react";
import type { ReactNode } from "react";

import type { Side } from "../../live/types";

interface Props {
  /** The small line on top: "The Hidden King". */
  eyebrow: ReactNode;
  /** The choice itself: "Pick 1". */
  title: ReactNode;
  tone?: Side | "accent";
  onPress?: () => void;
  isDisabled?: boolean;
  isPending?: boolean;
  isSelected?: boolean;
}

const TONE: Record<NonNullable<Props["tone"]>, { frame: string; eyebrow: string }> = {
  hk: {
    frame: "border-team-hk/40 bg-team-hk-soft text-team-hk-soft-foreground",
    eyebrow: "text-team-hk",
  },
  am: {
    frame: "border-team-am/40 bg-team-am-soft text-team-am-soft-foreground",
    eyebrow: "text-team-am",
  },
  accent: {
    frame: "border-accent/50 bg-accent-soft text-accent-soft-foreground",
    eyebrow: "text-accent",
  },
};

/** A big, tappable choice (the coinflip's four options, a scrim's sides). */
export function ChoiceCard({
  eyebrow,
  title,
  tone = "accent",
  onPress,
  isDisabled,
  isPending,
  isSelected,
}: Props) {
  const colours = TONE[tone];
  return (
    <Button
      variant="tertiary"
      onPress={onPress}
      isDisabled={isDisabled}
      isPending={isPending}
      aria-pressed={isSelected}
      className={`flex h-36 w-full flex-col items-start justify-between rounded-2xl border-2 p-5 text-left whitespace-normal ${colours.frame} ${
        isSelected ? "ring-2 ring-focus ring-offset-2 ring-offset-background" : ""
      }`}
    >
      <span className={`text-sm font-semibold ${colours.eyebrow}`}>{eyebrow}</span>
      <span className="text-xl font-bold">{title}</span>
    </Button>
  );
}
