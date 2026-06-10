import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/generate': 'http://localhost:8000',
      '/audio':    'http://localhost:8000',
      '/sounds':   'http://localhost:8000',
      '/ambient':  'http://localhost:8000',
      '/auth':     'http://localhost:8000',
    },
  },
})
