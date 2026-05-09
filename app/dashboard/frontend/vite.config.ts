import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy all /api requests to the Flask backend in development.
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        // Pass through Authorization headers for Bearer-token auth.
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            if (req.headers.authorization) {
              proxyReq.setHeader('Authorization', req.headers.authorization)
            }
          })
        },
      },
      // Proxy Socket.IO WebSocket upgrade
      '/socket.io': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        ws: true,
        configure: (proxy) => {
          // Suppress benign ECONNABORTED / ECONNREFUSED noise that appears when
          // the browser tears down a WebSocket connection mid-write, or when the
          // Flask backend is not yet running.
          proxy.on('error', (err: NodeJS.ErrnoException) => {
            if (err.code === 'ECONNABORTED' || err.code === 'ECONNREFUSED') return
            console.error('[socket.io proxy]', err.message)
          })
        },
      },
    },
  },
  build: {
    outDir: '../app/dashboard/static',
    emptyOutDir: true,
    // Phase 6 — 7.6: manual chunk splitting to maximise browser caching.
    // Each vendor group is hashed independently, so a React upgrade doesn't
    // bust the Ant Design or ECharts caches (and vice-versa).
    rollupOptions: {
      output: {
        manualChunks: {
          // React runtime — changes rarely
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          // Ant Design component library — large, changes on its own cadence
          'vendor-antd': ['antd'],
          // ECharts visualisation — very large, infrequently updated
          'vendor-echarts': ['echarts', 'echarts-for-react'],
          // State management + utilities
          'vendor-state': ['zustand', 'immer'],
          // Networking
          'vendor-network': ['axios', 'socket.io-client'],
        },
      },
    },
  },
})
