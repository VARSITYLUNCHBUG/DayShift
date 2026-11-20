// /me/share (E05): your share card, drawn by the server (/api/me/share.png, 1200 × 630). The
// toggles reload it; Download saves the PNG; Copy image puts it on the clipboard where the
// browser can (hidden where it can't).
import { Checkbox } from "@heroui/react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { queries, shareCardUrl } from "../../api/queries";
import type { ShareParts } from "../../api/queries";
import { Button, buttonClass } from "../../components/Button";
import { Icon } from "../../components/Icon";
import { PageHeader } from "../../components/Layout";
import { errorText, notify } from "../../components/toast";
import { number } from "../../lib/format";
import { BackLink } from "../shared/parts";

/** Whether this browser can put a PNG on the clipboard. */
export function canCopyImages(): boolean {
  return typeof window !== "undefined" && typeof window.ClipboardItem === "function" && "clipboard" in navigator && typeof navigator.clipboard.write === "function";
}

async function copyImage(url: string): Promise<void> {
  // A promise of the blob keeps Safari's user-gesture rule happy.
  const blob = fetch(url, { credentials: "same-origin" }).then((response) => {
    if (!response.ok) throw new Error("The card didn't draw. Try again.");
    return response.blob();
  });
  await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
}

const PARTS: { key: keyof ShareParts; label: string }[] = [
  { key: "rating", label: "Rating and tier" },
  { key: "place", label: "Ladder place" },
  { key: "award", label: "Last award" },
];

export function ShareCardPage() {
  const profile = useQuery(queries.me(null));
  const [parts, setParts] = useState<ShareParts>({ rating: true, place: true, award: true });
  const [loaded, setLoaded] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [copying, setCopying] = useState(false);
  const url = shareCardUrl(parts);
  const p = profile.data;
  const lastAward = p?.recent.find((m) => m.award);
  const detail: Record<keyof ShareParts, string | null> = {
    rating: p ? `${number(p.rating)}${p.tier ? ` · ${p.tier}` : ""}` : null,
    place: p?.rank ? `#${p.rank}` : p ? "Not on the ladder yet" : null,
    award: lastAward ? `${lastAward.award === "mvp" ? "MVP" : "Key player"}, No. ${lastAward.match_id}` : p ? "None yet" : null,
  };

  return (
    <>
      <BackLink to="/me">Me</BackLink>
      <PageHeader title="Your share card" lead="A PNG of your season so far. Your page stays private; this is what you choose to post." />
      <figure className="m-0 flex flex-col gap-2">
        <div className="relative aspect-1200/630 w-full max-w-300 overflow-hidden rounded-panel border border-line bg-surface">
          {loaded !== url && failed !== url ? <div role="status" aria-label="Drawing your card" className="absolute inset-0 bg-raised" /> : null}
          {failed === url ? (
            <p role="alert" className="absolute inset-0 flex items-center justify-center p-6 text-center text-body text-muted">
              Your card didn&apos;t draw this time. Change a toggle or reload the page to try again.
            </p>
          ) : (
            <img
              key={url}
              src={url}
              alt={`Your share card: ${p?.player.name ?? "you"}${parts.rating && detail.rating ? `, ${detail.rating}` : ""}${parts.place && p?.rank ? `, #${p.rank} on the ladder` : ""}.`}
              width={1200}
              height={630}
              onLoad={() => setLoaded(url)}
              onError={() => setFailed(url)}
              className="relative block size-full object-contain"
            />
          )}
        </div>
        <figcaption className="text-label text-muted">1200 × 630, the size Discord and most sites use for a link preview.</figcaption>
      </figure>
      <div className="flex flex-wrap items-start gap-x-10 gap-y-5">
        <div className="flex flex-wrap gap-2.5">
          <a href={url} download="dayshift-card.png" className={buttonClass({ size: "lg" })}>
            <Icon name="upload" />
            Download PNG
          </a>
          {canCopyImages() ? (
            <Button
              kind="ghost"
              size="lg"
              icon="copy"
              isPending={copying}
              pendingLabel="Copying…"
              onPress={() => {
                setCopying(true);
                copyImage(url).then(
                  () => notify.success("Card copied", "Paste it into Discord."),
                  (reason: unknown) => notify.error(errorText(reason)),
                ).finally(() => setCopying(false));
              }}
            >
              Copy image
            </Button>
          ) : null}
        </div>
        <fieldset className="flex flex-col gap-2">
          <legend className="pb-2 text-label font-extrabold">On the card</legend>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            {PARTS.map((part) => (
              <Checkbox
                key={part.key}
                isSelected={parts[part.key]}
                onChange={(on) => setParts((old) => ({ ...old, [part.key]: on }))}
                className="min-h-11"
              >
                <Checkbox.Control>
                  <Checkbox.Indicator />
                </Checkbox.Control>
                <Checkbox.Content>
                  <span className="flex flex-col">
                    <b className="text-label font-extrabold">{part.label}</b>
                    {detail[part.key] ? <span className="text-caption text-muted">{detail[part.key]}</span> : null}
                  </span>
                </Checkbox.Content>
              </Checkbox>
            ))}
          </div>
        </fieldset>
      </div>
    </>
  );
}

export default ShareCardPage;
