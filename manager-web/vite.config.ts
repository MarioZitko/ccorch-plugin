import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Built files are shipped inside the plugin and served by manager/server.py.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "../plugins/ccorch/manager/static", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:7420" } },
});
