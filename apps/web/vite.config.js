import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the React app runs on :5173 and forwards every /api call to the
// FastAPI backend, so the browser sees one origin and no CORS setup is needed.
const API_URL = process.env.BIOVERSE_API_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: API_URL, changeOrigin: true },
    },
  },
  preview: {
    port: 4173,
    proxy: {
      "/api": { target: API_URL, changeOrigin: true },
    },
  },
});
