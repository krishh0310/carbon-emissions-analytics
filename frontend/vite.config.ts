import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // maplibre-gl v6 loads its worker as a sibling ESM file; pre-bundling breaks that relative URL
  optimizeDeps: { exclude: ["maplibre-gl"] },
  server: { port: 5173, proxy: { "/api": process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000" } },
  preview: { port: 4173, proxy: { "/api": process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000" } },
});
