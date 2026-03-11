import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'
import { CHUNK_SIZE_WARNING_LIMIT, resolveManualChunk } from './config/viteChunking'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './tests/setup.ts',
  },
  build: {
    chunkSizeWarningLimit: CHUNK_SIZE_WARNING_LIMIT,
    rollupOptions: {
      output: {
        manualChunks: resolveManualChunk,
      },
    },
  },
})
