import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 개발 중에는 API·로그인·Gradio(/demo) 요청을 FastAPI(8000)로 넘깁니다.
// 배포에서는 FastAPI가 dist를 직접 제공합니다.
const backend = "http://localhost:8000";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: false },
      "/auth": { target: backend, changeOrigin: false },
      "/demo": { target: backend, changeOrigin: false, ws: true },
    },
  },
});
