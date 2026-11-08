import vue from '@vitejs/plugin-vue'
import { alphaTab } from '@coderline/alphatab-vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), alphaTab()],
  server: {
    proxy: {
      '/api': {
        target: process.env.LINGPU_API_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  preview: {
    proxy: {
      '/api': { target: process.env.LINGPU_API_URL || 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
