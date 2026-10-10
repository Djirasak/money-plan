import js from '@eslint/js';
import globals from 'globals';

export default [
  { ignores: ['node_modules/**', '**/*.min.js', 'money_plan/static/js/vendor/**', 'staticfiles/**', 'coverage/**'] },
  js.configs.recommended,
  {
    files: ['money_plan/static/js/**/*.js'],
    languageOptions: { sourceType: 'script', globals: { ...globals.browser } },
  },
  {
    files: ['**/*.test.js', 'vitest.config.mjs', 'eslint.config.mjs'],
    languageOptions: { sourceType: 'module', globals: { ...globals.node, ...globals.browser } },
  },
];
