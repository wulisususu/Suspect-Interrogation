import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// 本地开发把请求转到板端的一体机服务。板端接口是 HTTPS 直出（自签证书），
// 必须 secure:false，否则代理会因证书链校验失败而 502。
// 目标地址从 .env.local 的 VITE_DEV_BACKEND 读取，默认走本机隧道 8080。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const developmentBackend = env.VITE_DEV_BACKEND || 'http://127.0.0.1:8080'
  const backendProxy = { target: developmentBackend, changeOrigin: true, secure: false }

  return {
    base: './',
    plugins: [vue()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/api': backendProxy,
        '/work': backendProxy,
        // 后端自身在根路径暴露 /health/live|ready，直接转发即可。
        '/health': backendProxy,
      },
    },
    build: { target: 'es2022', sourcemap: true },
  }
})
