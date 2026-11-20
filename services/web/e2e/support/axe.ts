// Accessibility checks with axe-core: no serious or critical violations of WCAG 2.2 A and AA.
// The full results are attached to the test, so a failure's report says exactly what and where.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];
const BLOCKING = new Set(["serious", "critical"]);

export async function expectNoA11yViolations(
  page: Page,
  options: { label?: string; include?: string; exclude?: string[] } = {},
): Promise<void> {
  let builder = new AxeBuilder({ page })
    .withTags(TAGS)
    // React Aria's off-screen toast announcer: after a toast closes it leaves a role=img that
    // points at the closed toast's title (a library quirk, not page content). Every rule still
    // runs on everything else.
    .exclude("[data-live-announcer]");
  if (options.include) builder = builder.include(options.include);
  for (const selector of options.exclude ?? []) builder = builder.exclude(selector);
  const results = await builder.analyze();
  const label = options.label ?? new URL(page.url()).pathname;
  await test.info().attach(`axe ${label}`, {
    body: JSON.stringify(results.violations, null, 2),
    contentType: "application/json",
  });
  const blocking = results.violations
    .filter((violation) => BLOCKING.has(violation.impact ?? ""))
    .map((violation) => ({
      rule: violation.id,
      impact: violation.impact,
      help: violation.help,
      count: violation.nodes.length,
      first: violation.nodes[0]?.html.slice(0, 160),
    }));
  // Soft: the test goes on, so one run lists every page's violations, and still fails at the end.
  expect.soft(blocking, `axe: serious or critical violations on ${label}`).toEqual([]);
}
