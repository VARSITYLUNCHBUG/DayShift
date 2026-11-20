// Self-hosted fonts (the CSP is font-src 'self'): Bricolage Grotesque with its optical-size axis
// for display, Figtree for everything else. Both are variable WOFF2 with font-display: swap.
import "@fontsource-variable/bricolage-grotesque/opsz.css";
import "@fontsource-variable/figtree/wght.css";
import "./theme/theme.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
