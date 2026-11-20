import { cn } from "../lib/cn";
import { IconButton } from "./Button";
import { notify } from "./toast";

interface Props {
  code: string;
  /** 64 in the scorebug, smaller in a phone footer. */
  size?: "lg" | "md";
  className?: string;
}

/** The lobby code (F03): Figtree 800, tracked out, read letter by letter by screen readers, always
 * next to Copy. Shown to the 12 players only; the server never sends it to spectators. */
export function LobbyCode({ code, size = "lg", className }: Props) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      notify.info(`Copied ${code}`);
    } catch {
      notify.error(new Error("Couldn't copy. Select the code and copy it yourself."));
    }
  };
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-3", className)}>
      <span className="sr-only">Lobby code: {code.split("").join(" ")}</span>
      <span
        aria-hidden="true"
        className={cn(
          "font-sans font-extrabold tracking-code tabular-nums select-all",
          size === "lg" ? "text-coin leading-none md:text-clock" : "text-coin leading-none",
        )}
      >
        {code}
      </span>
      <IconButton icon="copy" label="Copy the lobby code" onPress={() => void copy()} />
    </span>
  );
}
