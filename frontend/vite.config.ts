import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // In development the FastAPI server runs separately; production serves both from one origin.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
