import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The research deck talks to the FastAPI backend (default :8077). Proxy /api + /ws in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      "/api": "http://127.0.0.1:8077",
      "/ws": { target: "ws://127.0.0.1:8077", ws: true },
      "/webhooks": "http://127.0.0.1:8077",
    },
  },
});
