/** Short decorative text, such as a player's or hero's initials, drawn by CSS rather than written
 * into the page. It isn't part of any name: a control labelled "Haze, you want it" doesn't read
 * as "PK Haze…" to screen readers or to voice control (WCAG 2.5.3, label in name). */
export function Glyphs({ text, className }: { text: string; className?: string }) {
  return <span aria-hidden="true" data-glyphs={text} className={className ? `ds-glyphs ${className}` : "ds-glyphs"} />;
}
