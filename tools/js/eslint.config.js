"use strict";
const js = require("@eslint/js");
const sonarjs = require("eslint-plugin-sonarjs");

const nodeGlobals = {
  require: "readonly",
  module: "writable",
  __dirname: "readonly",
  process: "readonly",
  console: "readonly",
};

// The same limits as the Python code: cyclomatic complexity 6 (ruff C901), cognitive complexity 10 (complexipy).
const complexity = {
  complexity: ["error", 6],
  "sonarjs/cognitive-complexity": ["error", 10],
};

module.exports = [
  js.configs.recommended,
  {
    plugins: { sonarjs },
    rules: complexity,
  },
  {
    files: ["skills/recap/page/recap-lib.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "script", globals: { window: "readonly", module: "writable" } },
    rules: { "no-var": "error", "prefer-const": "error", eqeqeq: "error", "no-implicit-globals": "error" },
  },
  {
    files: ["skills/recap/page/*.test.js", "tools/js/eslint.config.js"],
    languageOptions: { ecmaVersion: 2022, sourceType: "commonjs", globals: nodeGlobals },
    rules: { "no-var": "error", "prefer-const": "error", eqeqeq: "error" },
  },
];
