/* HUD layer: decrypt-reveal text, live telemetry, cursor-reactive grid.

   The techniques here are the ones Canvas UI and border-beam package up for
   React. Reimplemented rather than installed, for the same reason as
   everything else in this app: no bundler, and the demo has to run with the
   wifi off. Each of these is a few dozen lines natively. */

(() => {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const GLYPHS = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#$%&/<>[]{}=+*";

  /* ── decrypt reveal ──────────────────────────────── */

  // Scrambles each character, then locks them in left to right. Only touches
  // text nodes, so nested markup (the gradient <em>) survives intact.
  function decrypt(el, duration = 900) {
    if (reduced) return;
    const nodes = [];
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walk.nextNode())) {
      if (n.textContent.trim()) nodes.push({ node: n, final: n.textContent });
    }
    if (!nodes.length) return;

    const total = nodes.reduce((s, x) => s + x.final.length, 0);
    const start = performance.now();

    function frame(now) {
      const p = Math.min((now - start) / duration, 1);
      const locked = Math.floor(p * total);
      let seen = 0;
      for (const item of nodes) {
        let out = "";
        for (let i = 0; i < item.final.length; i++) {
          const ch = item.final[i];
          if (seen + i < locked || ch === " ") out += ch;
          else out += GLYPHS[(Math.random() * GLYPHS.length) | 0];
        }
        item.node.textContent = out;
        seen += item.final.length;
      }
      if (p < 1) requestAnimationFrame(frame);
      else nodes.forEach((x) => (x.node.textContent = x.final));
    }
    requestAnimationFrame(frame);
  }

  /* ── telemetry strip ─────────────────────────────── */

  // Real numbers from the actual index, not decoration. The point of a readout
  // is that it reads out something.
  function telemetry() {
    const el = document.getElementById("telemetry");
    if (!el) return;
    const fields = [
      ["IDX", "4159", "researchers indexed"],
      ["VEC", "23112", "abstracts embedded"],
      ["DIM", "1536", "embedding dimensions"],
      ["YC", "6049", "companies mapped"],
      ["GAP", "13", "white-space clusters"],
    ];
    el.innerHTML =
      fields
        .map(([k, v, title]) => `<span title="${title}"><i>${k}</i>${v}</span>`)
        .join('<u aria-hidden="true">·</u>') + '<b class="tick" aria-hidden="true">▍</b>';
  }

  /* ── cursor-reactive grid ────────────────────────── */

  // The CSS grid is static; this moves a light under it that follows the
  // pointer, so the surface feels instrumented rather than printed.
  function gridLight() {
    if (reduced) return;
    const grid = document.querySelector(".techgrid");
    if (!grid) return;
    let tx = 50, ty = 20, x = 50, y = 20, raf = null;

    addEventListener(
      "pointermove",
      (e) => {
        tx = (e.clientX / innerWidth) * 100;
        ty = (e.clientY / innerHeight) * 100;
        if (!raf) raf = requestAnimationFrame(step);
      },
      { passive: true }
    );

    function step() {
      raf = null;
      x += (tx - x) * 0.08;
      y += (ty - y) * 0.08;
      grid.style.setProperty("--gx", x + "%");
      grid.style.setProperty("--gy", y + "%");
      if (Math.abs(tx - x) > 0.2 || Math.abs(ty - y) > 0.2) raf = requestAnimationFrame(step);
    }
  }

  /* ── boot ────────────────────────────────────────── */

  function start() {
    telemetry();
    gridLight();

    const hero = document.querySelector(".hero");
    if (hero) setTimeout(() => decrypt(hero, 1000), 260);

    // band titles decrypt as they scroll into view
    const titles = document.querySelectorAll(".band-title");
    if (titles.length && !reduced) {
      const io = new IntersectionObserver(
        (entries) => {
          entries.forEach((e) => {
            if (e.isIntersecting) {
              decrypt(e.target, 700);
              io.unobserve(e.target);
            }
          });
        },
        { root: document.getElementById("search-view"), threshold: 0.6 }
      );
      titles.forEach((t) => io.observe(t));
    }
  }

  document.readyState === "loading"
    ? addEventListener("DOMContentLoaded", start)
    : start();

  window.HUD = { decrypt };
})();
