import { defineConfig } from 'vite';

export default defineConfig({
  base: '/portal/',
  build: { sourcemap: false },
  server: {
    proxy: Object.fromEntries(['/auth', '/environment', '/releases', '/builds', '/audit', '/health'].map(
      path => [path, { target: 'http://127.0.0.1:8090', changeOrigin: false }]
    )),
  },
});
