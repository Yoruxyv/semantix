import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  cacheDir: '.vite-cache',

  define: {
    'import.meta.env.VITE_API_BASE_URL': JSON.stringify('http://localhost:8000'),
  },

  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },

  test: {
    coverage: {
      provider: 'v8',
      thresholds: {
        branches: 75,
        functions: 82,
        lines: 82,
        statements: 82,
      },
    },
    environment: 'jsdom',
    exclude: ['tests/e2e/**', '**/node_modules/**', '**/dist/**'],
    globals: true,
    setupFiles: ['./tests/setup.ts'],
  },
});
