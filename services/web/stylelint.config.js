// Raw colours live only in src/theme/theme.css; every other stylesheet uses its tokens.
/** @type {import("stylelint").Config} */
export default {
  extends: ["stylelint-config-standard"],
  rules: {
    "color-no-hex": true,
    "at-rule-no-unknown": [
      true,
      {
        ignoreAtRules: ["theme", "custom-variant", "utility", "variant", "apply", "source", "reference", "plugin", "config"],
      },
    ],
    "at-rule-no-deprecated": [true, { ignoreAtRules: ["apply"] }],
    "at-rule-prelude-no-invalid": [true, { ignoreAtRules: ["apply", "custom-variant", "utility", "variant", "source", "theme"] }],
    "custom-property-empty-line-before": null,
    "value-keyword-case": ["lower", { ignoreKeywords: ["Inter"] }],
    "import-notation": "string",
    "custom-property-pattern": null,
    "selector-class-pattern": null,
  },
  overrides: [
    {
      files: ["src/theme/theme.css"],
      rules: { "color-no-hex": null },
    },
  ],
};
