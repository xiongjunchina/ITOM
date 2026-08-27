import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendDir = dirname(fileURLToPath(import.meta.url));
const releaseRoot = resolve(frontendDir, '../release');
const pointer = JSON.parse(readFileSync(resolve(releaseRoot, 'current.json'), 'utf8')) as { schema_version: number; current: string };
if (pointer.schema_version !== 1 || !/^v[0-9A-Za-z.-]+\.json$/.test(pointer.current)) {
  throw new Error('Invalid ITOM current release pointer');
}
const currentRelease = JSON.parse(readFileSync(resolve(releaseRoot, 'releases', pointer.current), 'utf8'));

export default defineConfig({
  plugins: [react()],
  define: {
    __ITOM_RELEASE__: JSON.stringify(currentRelease),
  },
  server: {
    port: 5180,
    proxy: {
      '/api': {
        target: 'http://localhost:6800',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
});
