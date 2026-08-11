import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The API runs as a separate process in dev; this keeps the client on
    // same-origin /api paths so no CORS setup is needed.
    proxy: {
      '/api': 'http://localhost:3001',
    },
  },
})
