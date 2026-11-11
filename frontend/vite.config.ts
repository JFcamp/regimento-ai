import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// O frontend chama /api/*, que o Vite repassa ao backend FastAPI local (sem precisar de CORS em desenvolvimento).
const BACKEND = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // 127.0.0.1 explícito: "localhost" pode resolver para IPv6 (::1) e não bater com o backend
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
});
