import { Chip } from "@heroui/react";

// Tiers come from the rating system's settings; these are the default names.
const TIER_CLASS: Record<string, string> = {
  bronze: "bg-tier-bronze-soft text-tier-bronze",
  silver: "bg-tier-silver-soft text-tier-silver",
  gold: "bg-tier-gold-soft text-tier-gold",
  platinum: "bg-tier-platinum-soft text-tier-platinum",
  diamond: "bg-tier-diamond-soft text-tier-diamond",
};

export function TierChip({ tier }: { tier: string | null | undefined }) {
  if (!tier) return null;
  const known = TIER_CLASS[tier.toLowerCase()];
  return (
    <Chip size="sm" variant="soft" className={known ? `font-bold ${known}` : "font-bold"}>
      {tier}
    </Chip>
  );
}
