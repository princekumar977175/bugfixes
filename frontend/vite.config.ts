import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
const backendWsUrl = backendUrl.replace(/^http/, 'ws');

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/health': backendUrl,
      '/trains': backendUrl,
      '/sections': backendUrl,
      '/replay': backendUrl,
      '/stations': backendUrl,
      '/ws': {
        target: backendWsUrl,
        ws: true,
      },
    },
  },
});
