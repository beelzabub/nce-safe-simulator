import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/app/',
  build: {
    outDir: '../public/app',
    emptyOutDir: true,
  },
  server: {
    host: true,
    proxy: {
      '/api':         'http://localhost:80',
      '/interactive': 'http://localhost:80',
    },
  },
})
