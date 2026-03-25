import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
  server: {
    allowedHosts: true,
    port: 9488,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:9487',
        changeOrigin: true,
      },
    },
  },
})
