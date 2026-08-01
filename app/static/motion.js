/* Landing-page motion: a drifting constellation, scroll reveals, counting stats.

   The constellation is the product's mental model made literal — points in a
   space, linked when they are close enough to be related. It is the same idea
   the matching engine runs on, which is why it earns the pixels. */

(() => {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ── constellation ───────────────────────────────── */

  function constellation() {
    if (reduced) return;
    const canvas = document.createElement("canvas");
    canvas.id = "constellation";
    document.body.prepend(canvas);
    const ctx = canvas.getContext("2d");

    let w, h, dpr, pts;
    const LINK = 132;

    const accent = () =>
      getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#ff7a1a";

    function resize() {
      dpr = Math.min(devicePixelRatio || 1, 2);
      w = innerWidth;
      h = innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // density scaled to area so a big monitor doesn't get a sparse field
      const n = Math.min(96, Math.round((w * h) / 17000));
      pts = Array.from({ length: n }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.22,
        vy: (Math.random() - 0.5) * 0.22,
        r: Math.random() * 1.5 + 0.7,
        // a few points are "demand", the rest "supply" — same colour language
        // as the White Space Map
        hot: Math.random() < 0.18,
      }));
    }

    const mouse = { x: -999, y: -999 };
    addEventListener("pointermove", (e) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
    });
    addEventListener("pointerleave", () => {
      mouse.x = mouse.y = -999;
    });

    function frame() {
      ctx.clearRect(0, 0, w, h);
      const hot = accent();

      for (const p of pts) {
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < -20) p.x = w + 20;
        if (p.x > w + 20) p.x = -20;
        if (p.y < -20) p.y = h + 20;
        if (p.y > h + 20) p.y = -20;
      }

      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const a = pts[i], b = pts[j];
          const dx = a.x - b.x, dy = a.y - b.y;
          const d2 = dx * dx + dy * dy;
          if (d2 > LINK * LINK) continue;
          const t = 1 - Math.sqrt(d2) / LINK;
          ctx.strokeStyle = a.hot || b.hot ? hot : "#7b86b8";
          ctx.globalAlpha = t * 0.3;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }

      for (const p of pts) {
        // points near the cursor light up — the field reacts without the
        // page hijacking the pointer
        const dx = p.x - mouse.x, dy = p.y - mouse.y;
        const near = Math.max(0, 1 - Math.sqrt(dx * dx + dy * dy) / 160);
        ctx.globalAlpha = 0.28 + near * 0.62;
        ctx.fillStyle = p.hot ? hot : "#8791c4";
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r + near * 1.5, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.globalAlpha = 1;
      requestAnimationFrame(frame);
    }

    resize();
    addEventListener("resize", resize);
    requestAnimationFrame(frame);
  }

  /* ── scroll reveals ──────────────────────────────── */

  function reveals() {
    const targets = document.querySelectorAll(".band, .foot");
    targets.forEach((t) => t.classList.add("reveal"));
    if (reduced) {
      targets.forEach((t) => t.classList.add("is-in"));
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("is-in");
            io.unobserve(e.target);
          }
        });
      },
      // the landing view scrolls, not the window
      { root: document.getElementById("search-view"), threshold: 0.12 }
    );
    targets.forEach((t) => io.observe(t));
  }

  /* ── counting stats ──────────────────────────────── */

  function countUp() {
    const nums = document.querySelectorAll(".stats dt");
    nums.forEach((el) => {
      const target = parseInt(el.textContent.replace(/[^0-9]/g, ""), 10);
      if (!target || reduced) return;
      el.dataset.final = el.textContent;
      let start = null;
      const dur = 1100;
      const step = (ts) => {
        if (!start) start = ts;
        const p = Math.min((ts - start) / dur, 1);
        // ease-out so it decelerates into the real number
        const v = Math.round(target * (1 - Math.pow(1 - p, 3)));
        el.textContent = v.toLocaleString();
        if (p < 1) requestAnimationFrame(step);
        else el.textContent = el.dataset.final;
      };
      requestAnimationFrame(step);
    });
  }

  function start() {
    constellation();
    reveals();
    // count only once the strip is actually on screen
    const strip = document.querySelector(".stats");
    if (!strip) return;
    const io = new IntersectionObserver(
      (e) => {
        if (e[0].isIntersecting) {
          countUp();
          io.disconnect();
        }
      },
      { root: document.getElementById("search-view"), threshold: 0.4 }
    );
    io.observe(strip);
  }

  /* ── cursor spotlight ────────────────────────────── */

  // One delegated listener rather than per-element: the deck rebuilds its
  // cards on every swipe, and re-binding each time leaks handlers.
  const SPOT = ".step, .ws-cluster-item, .sl-item, .card-block, .claim-item, .msg-item";

  function spotlight() {
    if (reduced) return;
    document.addEventListener(
      "pointermove",
      (e) => {
        const el = e.target.closest?.(SPOT);
        if (!el) return;
        if (!el.classList.contains("spotlight")) el.classList.add("spotlight");
        const r = el.getBoundingClientRect();
        el.style.setProperty("--mx", `${e.clientX - r.left}px`);
        el.style.setProperty("--my", `${e.clientY - r.top}px`);
      },
      { passive: true }
    );
  }

  /* ── swipe-card tilt ─────────────────────────────── */

  // Parallax tilt on the top card. Only touches cards that aren't mid-drag,
  // since the drag handler owns `transform` while a swipe is in flight.
  function cardTilt() {
    if (reduced) return;
    const deck = document.getElementById("deck");
    if (!deck) return;

    deck.addEventListener(
      "pointermove",
      (e) => {
        const card = deck.lastElementChild;
        if (!card || !card.classList.contains("card") || card.dataset.dragging) return;
        const r = card.getBoundingClientRect();
        const dx = (e.clientX - r.left) / r.width - 0.5;
        const dy = (e.clientY - r.top) / r.height - 0.5;
        card.style.transform =
          `perspective(1000px) rotateY(${dx * 9}deg) rotateX(${-dy * 9}deg) translateZ(6px)`;
        card.style.setProperty("--mx", `${e.clientX - r.left}px`);
        card.style.setProperty("--my", `${e.clientY - r.top}px`);
        card.classList.add("spotlight");
      },
      { passive: true }
    );

    deck.addEventListener("pointerleave", () => {
      const card = deck.lastElementChild;
      if (card && card.classList.contains("card") && !card.dataset.dragging) {
        card.style.transform = "";
      }
    });
  }

  document.readyState === "loading"
    ? addEventListener("DOMContentLoaded", () => {
        start();
        spotlight();
        cardTilt();
      })
    : (start(), spotlight(), cardTilt());
})();
