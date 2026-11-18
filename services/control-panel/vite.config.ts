import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type ProxyOptions } from "vite";

/** Where `npm run mock` listens; `--mode mock` points both proxies at it. */
const MOCK = "http://127.0.0.1:18099";

// Same routing as nginx.conf: the browser only ever talks to the panel's origin. The targets
// default to the dev stack's host ports and can be moved with PANEL_CONTROL_TARGET and
// PANEL_SIM_TARGET.
function proxies(mode: string): Record<string, ProxyOptions> {
  const env = loadEnv(mode, process.cwd(), "PANEL_");
  const mock = mode === "mock" ? MOCK : undefined;
  const control = env.PANEL_CONTROL_TARGET || mock || "http://127.0.0.1:18000";
  const sim = env.PANEL_SIM_TARGET || mock || "http://127.0.0.1:18090";
  return {
    "/_control/": { target: control, changeOrigin: true },
    "/_sim/": { target: sim, changeOrigin: true },
  };
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), tailwindcss()],
  server: { host: "127.0.0.1", port: 5174, strictPort: true, proxy: proxies(mode) },
  preview: { host: "127.0.0.1", port: 4174, strictPort: true, proxy: proxies(mode) },
  // The entry chunk is React, React Aria and HeroUI; screens load on demand. The limit warns
  // when the entry outgrows that (about 200 KB gzipped).
  build: { sourcemap: true, chunkSizeWarningLimit: 700 },
  // API and lib tests run in node; component tests opt into jsdom with a docblock.
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
}));
