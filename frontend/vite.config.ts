import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { CHUNK_SIZE_WARNING_LIMIT, resolveManualChunk } from './config/viteChunking'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: CHUNK_SIZE_WARNING_LIMIT,
    rollupOptions: {
      output: {
        manualChunks: resolveManualChunk,
      },
    },
  },
})
