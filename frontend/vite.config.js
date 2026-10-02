import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';

export default defineConfig(({command}) => ({
  plugins: [react()],
  base: command === 'serve' ? '/' : '/static/webui/',
  server: {proxy: {'/api': 'http://127.0.0.1:8765'}},
  build: {
    outDir: '../src/codex_token_report/static/webui',
    emptyOutDir: true,
    rollupOptions: {
      input: fileURLToPath(new URL('./src/main.jsx', import.meta.url)),
      output: {
        entryFileNames: 'app.js', chunkFileNames: '[name]-[hash].js',
        assetFileNames: asset => asset.names?.some(name => name.endsWith('.css')) || asset.name?.endsWith('.css')
          ? 'styles.css' : '[name]-[hash][extname]',
      },
    },
  },
  test: {environment: 'jsdom', setupFiles: ['./src/test/setup.js'], restoreMocks: true},
}));
