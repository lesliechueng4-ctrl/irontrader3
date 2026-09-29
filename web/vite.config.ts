import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 新版前端挂在站点根路径（Flask 托管 web/dist）；dev 模式下 /api 代理到 Flask
export default defineConfig({
  base: '/',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5002',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // 拆出体积大的第三方库：首屏不需要的 ECharts 随日内抽屉按需加载
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom', '@tanstack/react-query'],
          antd: ['antd', '@ant-design/icons', 'dayjs'],
          echarts: ['echarts', 'echarts-for-react'],
        },
      },
    },
  },
});
