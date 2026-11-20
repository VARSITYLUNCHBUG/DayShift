import { cn } from "../../lib/cn";

/** The hero art's credit, at the foot of every page that shows it. The art is the game's own. */
export function ArtCredit({ className }: { className?: string }) {
  return (
    <footer className={cn("mx-auto box-border flex w-full max-w-room justify-end px-4 pb-6 text-micro text-faint md:px-8", className)}>
      <span>Hero art © Valve</span>
    </footer>
  );
}
