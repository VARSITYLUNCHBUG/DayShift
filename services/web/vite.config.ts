/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Django (uvicorn) runs on 8000 in development. Everything that isn't the web app itself goes
// there; the session cookie is shared because cookies ignore the port.
const DJANGO = "http://127.0.0.1:8000";
const PROXIED = ["/api", "/auth", "/avatar", "/static/hero-art", "/admin", "/_control"];

export default defineConfig(({ command }) => ({
  // Django serves the build through WhiteNoise from STATIC_URL + "web/".
  base: command === "build" ? "/static/web/" : "/",
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      ...Object.fromEntries(PROXIED.map((path) => [path, { target: DJANGO, changeOrigin: false }])),
      "/ws": { target: DJANGO, ws: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    target: "es2022",
    rolldownOptions: {
      output: {
        // Entries-aware chunks are named after every page that shares them; keep the file names short.
        chunkFileNames: (chunk) => `assets/${chunk.name.split("~")[0]}-[hash].js`,
        // Libraries change less often than the app, so they get files of their own that stay
        // cached across deploys: React and the router, React Aria with HeroUI, then the rest.
        // The last two are entries-aware: split by which pages use them, so the first load
        // carries only what the shell needs and each page brings its own share.
        codeSplitting: {
          groups: [
            {
              name: "react",
              test: /node_modules[\\/](react|react-dom|scheduler|react-router)[\\/]/,
              priority: 3,
            },
            {
              name: "ui",
              test: /node_modules[\\/](react-aria|react-aria-components|react-stately|@react-aria|@react-stately|@react-types|@internationalized|@heroui|@radix-ui|tailwind-variants|tailwind-merge)[\\/]/,
              priority: 2,
              entriesAware: true,
              entriesAwareMergeThreshold: 20_000,
            },
            { name: "vendor", test: /node_modules/, priority: 1, entriesAware: true, entriesAwareMergeThreshold: 20_000 },
          ],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    restoreMocks: true,
    // Route tests load lazy pages (and the old screens behind them) on first use; under a full
    // parallel run that can take a few seconds in jsdom.
    testTimeout: 15_000,
  },
}));
