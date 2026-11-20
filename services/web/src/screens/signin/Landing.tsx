// The sign-in page's call to action, as staff set it in the admin (league/services/landing.py):
// a tagline, and a message of the day or advert. Both HTML bodies come cleaned to an allow-list
// on the server, so they're inserted as they are; the CSP is the second line.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { ReactNode } from "react";

import { queries } from "../../api/queries";
import type { Advert } from "../../api/types";
import { Icon } from "../../components/Icon";
import { cn } from "../../lib/cn";
import { useMediaQuery } from "../../lib/useMediaQuery";

/** The tagline and advert, when staff have set them. Until it loads, or if it can't, neither. */
export function useLanding() {
  return useQuery(queries.landing()).data ?? null;
}

/** Copy written in the admin, in the page's own type (theme.css `.ds-rich`). */
const RICH = "ds-rich";

/** A tagline's first paragraph, as the page's headline in its biggest type (theme.css `.ds-headline`). */
export function Headline({ id, html }: { id: string; html: string }) {
  // Cleaned on the server (league/services/landing.py): safe to insert as it is.
  return <h1 id={id} className="ds-headline type-display text-poster break-words max-md:text-board" dangerouslySetInnerHTML={{ __html: html }} />;
}

/** The lines under the headline. */
export function Tagline({ html }: { html: string }) {
  // Cleaned on the server (league/services/landing.py): safe to insert as it is.
  return <div className={cn(RICH, "max-w-lead text-lead-lg text-muted")} dangerouslySetInnerHTML={{ __html: html }} />;
}

function Linked({ href, children }: { href: string | null; children: ReactNode }) {
  if (!href) return <>{children}</>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="block rounded-card focus-visible:outline-2 focus-visible:outline-offset-2">
      {children}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

/** A YouTube video, loaded only when pressed: until then nothing is fetched from YouTube. */
function YouTube({ id, title }: { id: string; title: string }) {
  const [playing, setPlaying] = useState(false);
  if (playing) {
    return (
      <iframe
        src={`https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0`}
        title={title || "Video"}
        allow="autoplay; encrypted-media; picture-in-picture; fullscreen"
        allowFullScreen
        referrerPolicy="strict-origin-when-cross-origin"
        className="aspect-video w-full rounded-card border-0"
      />
    );
  }
  return (
    <button
      type="button"
      onClick={() => setPlaying(true)}
      className="flex aspect-video w-full flex-col items-center justify-center gap-3 rounded-card bg-raised px-4 text-center transition-state hover:bg-raised-2"
    >
      <span className="flex size-16 items-center justify-center rounded-full bg-brand text-brand-ink">
        <Icon name="play" size={28} />
      </span>
      <span className="text-body font-bold">{title || "Play the video"}</span>
      <span className="text-caption text-muted">Plays from YouTube</span>
    </button>
  );
}

function Media({ advert }: { advert: Advert }) {
  // Moving pictures wait to be asked for when the viewer has asked for less motion.
  const still = useMediaQuery("(prefers-reduced-motion: reduce)");
  switch (advert.kind) {
    case "image":
      return advert.src ? (
        <Linked href={advert.link_url}>
          <img src={advert.src} alt={advert.alt} loading="lazy" decoding="async" className="h-auto w-full rounded-card" />
        </Linked>
      ) : null;
    case "video":
      return advert.src ? (
        <video
          src={advert.src}
          aria-label={advert.alt}
          autoPlay={!still}
          controls={still}
          muted
          loop
          playsInline
          preload="metadata"
          className="aspect-video w-full rounded-card bg-raised object-cover"
        />
      ) : null;
    case "youtube":
      return advert.youtube_id ? <YouTube id={advert.youtube_id} title={advert.alt} /> : null;
    case "html":
      return advert.html ? (
        // Cleaned on the server (league/services/landing.py): safe to insert as it is.
        <div className={cn(RICH, "text-body text-muted")} dangerouslySetInnerHTML={{ __html: advert.html }} />
      ) : null;
  }
}

/** The message of the day or advert, in a card under the tagline. */
export function AdvertCard({ advert }: { advert: Advert }) {
  const media = <Media advert={advert} />;
  return (
    <section aria-label="Message of the day" className={cn("w-full", advert.kind === "html" && "rounded-card border border-line bg-surface p-5")}>
      {advert.kind === "video" || advert.kind === "youtube" ? (
        <div className="flex flex-col gap-2">
          {media}
          {advert.link_url ? (
            <a href={advert.link_url} target="_blank" rel="noopener noreferrer" className="self-start text-label font-bold underline underline-offset-2">
              Find out more
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          ) : null}
        </div>
      ) : (
        media
      )}
    </section>
  );
}
