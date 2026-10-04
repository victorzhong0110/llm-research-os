import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built assets are shipped inside the wheel and served by the local API,
// so the build output goes into the Python package rather than a web root.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/llm_research_os/web/static",
    emptyOutDir: true,
    sourcemap: false,
    // A single bundle keeps the wheel small and the server's asset map trivial.
    rollupOptions: {
      output: {
        manualChunks: undefined,
        entryFileNames: "assets/[name]-[hash].js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
});
