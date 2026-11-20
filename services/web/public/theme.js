// Applies the saved theme before the first paint. HeroUI's useTheme keeps it under this key;
// src/theme/ThemeContext.tsx takes over once React runs. Dark is the default.
(function () {
  var theme = "dark";
  try {
    theme = localStorage.getItem("heroui-theme") || "dark";
  } catch (e) {
    // Storage blocked: stay dark.
  }
  if (theme === "system") {
    theme = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  }
  if (theme !== "light") return;
  var root = document.documentElement;
  root.classList.remove("dark");
  root.classList.add("light");
  root.setAttribute("data-theme", "light");
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", "#F6F2EA");
})();
