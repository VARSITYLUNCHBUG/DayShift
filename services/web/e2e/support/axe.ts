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
  let builder = new AxeBuilder({ page }).withTags(TAGS);
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
      targets: violation.nodes.slice(0, 5).map((node) => node.target.join(" ")),
    }));
  expect(blocking, `axe: serious or critical violations on ${label}`).toEqual([]);
}
