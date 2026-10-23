import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
// @ts-expect-error plain JS module, only used by `vite serve`
import fixtures from './dev/fixture-plugin.mjs';

export default defineConfig(({ command }) => ({
  base: '/',
  plugins: [
    react(),
    // Fixture mode never reaches the build and stays off under vitest.
    ...(command === 'serve' && !process.env.VITEST ? [fixtures()] : []),
  ],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
  test: {
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    environment: 'node',
  },
}));
