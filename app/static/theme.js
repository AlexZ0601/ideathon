/* Explicit theme control.

   Before this, the palette followed prefers-color-scheme only — which is why
   the app looked white on one machine and black on another, and flipped by
   itself when macOS switched appearance at sunset. Auto is still the default,
   but now it's a choice rather than the only behaviour, and it survives a
   reload.

   Loaded before the stylesheet paints so there is no light-to-dark flash. */

(() => {
  const KEY = "cofoundr.theme";
  const ORDER = ["auto", "light", "dark"];
  const ICON = { auto: "◐", light: "☀", dark: "☾" };
  const LABEL = { auto: "Match system", light: "Light", dark: "Dark" };

  let mode = "auto";
  try {
    const saved = localStorage.getItem(KEY);
    if (ORDER.includes(saved)) mode = saved;
  } catch {
    /* private browsing — auto is a fine fallback */
  }

  function apply() {
    const root = document.documentElement;
    if (mode === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", mode);
    // shaders sample the CSS variables, so they need a nudge after the swap
    requestAnimationFrame(() => window.GradientBG?.refresh());
  }

  apply();

  function paint(btn) {
    btn.textContent = ICON[mode];
    btn.title = `Theme: ${LABEL[mode]} (click to change)`;
    btn.setAttribute("aria-label", `Theme: ${LABEL[mode]}. Click to change.`);
  }

  function mount() {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    paint(btn);
    btn.onclick = () => {
      mode = ORDER[(ORDER.indexOf(mode) + 1) % ORDER.length];
      try {
        localStorage.setItem(KEY, mode);
      } catch {
        /* not persisting is survivable */
      }
      apply();
      paint(btn);
    };
  }

  document.readyState === "loading"
    ? document.addEventListener("DOMContentLoaded", mount)
    : mount();
})();
