import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import path from 'path';

function apiProxy(target: string) {
  return {
    target,
    bypass(req: { headers?: { accept?: string } }) {
      if (req.headers?.accept?.includes('text/html')) {
        return '/index.html';
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/health': apiProxy('http://127.0.0.1:8000'),
      '/runs': apiProxy('http://127.0.0.1:8000'),
      '/reports': apiProxy('http://127.0.0.1:8000'),
      '/metadata': apiProxy('http://127.0.0.1:8000'),
      '/aurum-assistant': apiProxy('http://127.0.0.1:8000'),
      '/assistant': apiProxy('http://127.0.0.1:8000'),
      '/custom-checks': apiProxy('http://127.0.0.1:8000'),
      '/projects': apiProxy('http://127.0.0.1:8000'),
      '/datasets': apiProxy('http://127.0.0.1:8000'),
      '/connectors': apiProxy('http://127.0.0.1:8000'),
    },
  },
});
