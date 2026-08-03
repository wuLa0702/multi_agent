/// <reference types="vitest/config" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// API 代理目标：本地开发后端 8010（8000 被遗留进程占用，2026-08-02 拍板）
// VITE_API_PROXY 覆盖（scripts/dev.sh 启动前端时显式传入；云端部署时指容器地址）
const apiProxy = process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8010'

export default defineConfig({
  plugins: [tailwindcss(), react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5176,
    proxy: {
      '/v1': apiProxy,
      '/health': apiProxy,
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
