import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/auth": "http://127.0.0.1:8000",
      "/query": "http://127.0.0.1:8000",
      "/dashboard": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/summarize": "http://127.0.0.1:8000",
      "/vision": "http://127.0.0.1:8000",
      "/input": "http://127.0.0.1:8000",
      "/knowledge": "http://127.0.0.1:8000"
    }
  }
});
