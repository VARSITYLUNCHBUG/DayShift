// Lint rules, including the ones that hold the design system: colours come from theme tokens
// (src/theme/theme.css is the only file with raw colours), no arbitrary Tailwind values, and
// clicks only on elements that are interactive (HeroUI's components take onPress).
import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

const HEX_COLOUR = "^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$";
const INLINE_HEX = "[:(]\\s*#[0-9a-fA-F]{3,8}\\b";
const ARBITRARY_VALUE = "-\\[";
const NON_INTERACTIVE =
  "^(div|span|p|li|ul|ol|dl|dt|dd|section|article|main|header|footer|nav|aside|figure|img|svg|h[1-6]|table|thead|tbody|tr|td|th|label|form|fieldset)$";
const POINTER_HANDLER = "^on(Click|DoubleClick|MouseDown|MouseUp|KeyDown|KeyUp|KeyPress)$";

const designRules = [
  {
    selector: `Literal[value=/${HEX_COLOUR}/]`,
    message: "Use a theme token (bg-accent, text-team-hk, …), not a hex colour.",
  },
  {
    selector: `Literal[value=/${INLINE_HEX}/]`,
    message: "Use a theme token, not a hex colour.",
  },
  {
    selector: `TemplateElement[value.raw=/${INLINE_HEX}/]`,
    message: "Use a theme token, not a hex colour.",
  },
  {
    selector: `Literal[value=/${ARBITRARY_VALUE}/]`,
    message: "No arbitrary Tailwind values (`-[…]`): use the spacing scale or a theme token.",
  },
  {
    selector: `TemplateElement[value.raw=/${ARBITRARY_VALUE}/]`,
    message: "No arbitrary Tailwind values (`-[…]`): use the spacing scale or a theme token.",
  },
  {
    selector: `JSXOpeningElement[name.name=/${NON_INTERACTIVE}/] > JSXAttribute[name.name=/${POINTER_HANDLER}/]`,
    message: "Only interactive elements take clicks: use a HeroUI Button or Link with onPress.",
  },
];

export default defineConfig(
  { ignores: ["dist", "node_modules", "public", "src/live/protocol.gen.ts", "src/live/protocol.legacy.ts", "test-results", "playwright-report"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        projectService: { allowDefaultProject: ["vite.config.ts", "playwright.config.ts"] },
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.flat.recommended.rules,
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_", destructuredArrayIgnorePattern: "^_" }],
      "@typescript-eslint/consistent-type-imports": "error",
      "@typescript-eslint/no-misused-promises": ["error", { checksVoidReturn: { attributes: false } }],
      "@typescript-eslint/no-confusing-void-expression": ["error", { ignoreArrowShorthand: true }],
      // Template strings with numbers are how the copy is written ("Pick 4 of 12").
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
    },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    rules: { "no-restricted-syntax": ["error", ...designRules] },
  },
  {
    // The old screens (src/legacy) were written against the recommended set. They compile and keep
    // their tests until FE-ROOM and FE-PAGES replace them; the strict extras stay off there.
    files: ["src/legacy/**/*.{ts,tsx}"],
    rules: {
      "@typescript-eslint/no-unnecessary-condition": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
      "@typescript-eslint/restrict-template-expressions": "off",
      "@typescript-eslint/no-confusing-void-expression": "off",
      "@typescript-eslint/no-unnecessary-type-parameters": "off",
      "@typescript-eslint/no-extraneous-class": "off",
      "@typescript-eslint/no-unnecessary-type-conversion": "off",
      "@typescript-eslint/use-unknown-in-catch-callback-variable": "off",
      "@typescript-eslint/no-deprecated": "off",
      "@typescript-eslint/no-dynamic-delete": "off",
      "@typescript-eslint/no-invalid-void-type": "off",
      "@typescript-eslint/unified-signatures": "off",
    },
  },
  {
    files: ["**/*.test.{ts,tsx}", "src/test/**", "src/dev/**", "src/legacy/dev/**"],
    rules: {
      "@typescript-eslint/unbound-method": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  },
  {
    files: ["**/*.{js,mjs}"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
);
