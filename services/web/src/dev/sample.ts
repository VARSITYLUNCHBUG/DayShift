// The example night the wireframe uses everywhere (design/dayshift/wireframe/ds.py): match No. 413,
// Wednesday league night. Rook (you) captains Rook's Team (The Hidden King) against Vesper's Team
// (The Archmother). For the gallery and component tests only.
import type { DraftStep } from "../components/DraftStrip";
import type { HeroChoice } from "../components/HeroGrid";
import type { TeamKey } from "../components/team";

export const ME = "Rook";
export const MATCH_NO = "No. 413";
export const NIGHT = "Wednesday league night";

export interface SamplePlayer {
  id: string;
  tag: string;
  name: string;
  hero: string;
  team: TeamKey;
}

const HK: [string, string, string][] = [
  ["OWL", "Rook", "Abrams"],
  ["OWL", "Pike", "Ivy"],
  ["KRK", "Mothball", "Mirage"],
  ["VLT", "Tikka", "Viscous"],
  ["PXL", "Lumen", "Holliday"],
  ["DRT", "Quill", "Warden"],
];
const AM: [string, string, string][] = [
  ["MSN", "Vesper", "Dynamo"],
  ["MSN", "Juniper", "Infernus"],
  ["ZPH", "Azimuth", "Paradox"],
  ["ZPH", "Exo", "Lady Geist"],
  ["GLD", "Halcyon", "Pocket"],
  ["GLD", "Brindle", "Yamato"],
];

function players(rows: [string, string, string][], team: TeamKey, start: number): SamplePlayer[] {
  return rows.map(([tag, name, hero], i) => ({ id: String(start + i), tag, name, hero, team }));
}

export const HK_PLAYERS = players(HK, "hk", 1);
export const AM_PLAYERS = players(AM, "am", 7);

/** The hero art pack's URL for a hero ("Lady Geist" → /static/hero-art/lady-geist.webp). */
export function heroArt(name: string): string {
  const slug = name.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return `/static/hero-art/${slug}.webp`;
}

export const HEROES = [
  "Abrams", "Apollo", "Bebop", "Calico", "Dynamo", "Grey Talon", "Haze", "Holliday", "Infernus", "Ivy",
  "Kelvin", "Lady Geist", "Lash", "McGinnis", "Mirage", "Mo & Krill", "Paradox", "Pocket", "Seven",
  "Viscous", "Warden", "Wraith", "Yamato", "Vindicta",
];

/** The hero draft at step 8 (Rook's second pick): bans and picks so far, Pike's wish on Ivy. */
export function heroChoices(): HeroChoice[] {
  const banned = new Set(["Haze", "Wraith", "Seven", "Lash"]);
  const hkPicks = new Set(["Abrams"]);
  const amPicks = new Set(["Dynamo", "Infernus"]);
  return HEROES.map((name) => ({
    id: name,
    name,
    art: heroArt(name),
    state: banned.has(name) ? "banned" : hkPicks.has(name) ? "hk" : amPicks.has(name) ? "am" : "free",
    tag: hkPicks.has(name) ? "Rook's Team" : amPicks.has(name) ? "Vesper's Team" : name === "Ivy" ? "Pike wants her" : undefined,
    tagTone: hkPicks.has(name) ? "hk" : amPicks.has(name) ? "am" : "muted",
    wishes: name === "Ivy" ? "PK" : name === "Mirage" ? "QL" : null,
  }));
}

const ORDER = ["B1", "B2", "B1", "B2", "P1", "P2", "P2", "P1", "P2", "P1", "B2", "B1", "P2", "P1", "P1", "P2", "P1", "P2"];
const DONE = ["Haze", "Wraith", "Seven", "Lash", "Abrams", "Dynamo", "Infernus"];

export const DRAFT_STEPS: DraftStep[] = ORDER.map((step, i) => ({
  kind: step.startsWith("B") ? "ban" : "pick",
  team: step.endsWith("1") ? "hk" : "am",
  hero: DONE[i] ?? null,
}));

/** A soul lead over 31:12: Vesper's Team early, Rook's Team from about 9:00. */
export const SOUL_LEAD = Array.from({ length: 157 }, (_, i) => {
  const t = i * 12;
  const minutes = t / 60;
  return { t, lead: Math.round(9000 * Math.sin(minutes / 4.2 - 2) + 1200 * minutes - 6000) };
});

/** A deadline this many seconds from now, as the server would send it. */
export function inSeconds(seconds: number): string {
  return new Date(Date.now() + seconds * 1000).toISOString();
}
