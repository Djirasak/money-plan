import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['money_plan/static/js/tests/**/*.test.js'],
    coverage: {
      provider: 'v8',
      include: ['money_plan/static/js/project.js'],
      reporter: ['text'],
    },
  },
});
