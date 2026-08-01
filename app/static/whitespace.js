/* White Space Map — WebGL point cloud of supply vs demand.

   Hand-rolled rather than deck.gl on purpose: the demo has to run with wifi
   off, and deck.gl means either a CDN script or a bundler. This is ~10k
   gl.POINTS in two draw calls, which needs neither. */

(() => {
  const $ = (id) => document.getElementById(id);

  const VERT = `
    attribute vec3 aPos;
    attribute vec3 aColor;
    attribute float aSize;
    uniform mat4 uMVP;
    uniform float uScale;
    varying vec3 vColor;
    varying float vFade;
    void main() {
      vec4 clip = uMVP * vec4(aPos, 1.0);
      gl_Position = clip;
      // shrink with distance so the cloud reads as volumetric
      float d = max(clip.w, 0.15);
      gl_PointSize = clamp(aSize * uScale / d, 1.0, 26.0);
      vColor = aColor;
      vFade = clamp(1.6 / d, 0.12, 1.0);
    }`;

  const FRAG = `
    precision mediump float;
    varying vec3 vColor;
    varying float vFade;
    void main() {
      vec2 c = gl_PointCoord - vec2(0.5);
      float r = dot(c, c);
      if (r > 0.25) discard;
      float glow = smoothstep(0.25, 0.0, r);
      gl_FragColor = vec4(vColor, glow * vFade);
    }`;

  /* ── tiny matrix helpers ─────────────────────────── */

  // column-major, matching WebGL: element (row r, col c) lives at c*4 + r
  const mul = (a, b) => {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++)
      for (let r = 0; r < 4; r++) {
        let s = 0;
        for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
        o[c * 4 + r] = s;
      }
    return o;
  };

  const perspective = (fov, aspect, near, far) => {
    const f = 1 / Math.tan(fov / 2);
    return new Float32Array([
      f / aspect, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far + near) / (near - far), -1,
      0, 0, (2 * far * near) / (near - far), 0,
    ]);
  };

  const lookAt = (eye, target) => {
    const up = [0, 1, 0];
    const z = norm3([eye[0] - target[0], eye[1] - target[1], eye[2] - target[2]]);
    const x = norm3(cross(up, z));
    const y = cross(z, x);
    return new Float32Array([
      x[0], y[0], z[0], 0,
      x[1], y[1], z[1], 0,
      x[2], y[2], z[2], 0,
      -dot3(x, eye), -dot3(y, eye), -dot3(z, eye), 1,
    ]);
  };

  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const norm3 = (v) => {
    const l = Math.hypot(...v) || 1;
    return [v[0] / l, v[1] / l, v[2] / l];
  };

  /* ── state ───────────────────────────────────────── */

  let gl, prog, canvas, data;
  const buffers = {};
  const cam = { az: 0.7, el: 0.35, r: 3.1, tx: 0, ty: 0, tz: 0 };
  const target = { ...cam };
  let showSupply = true;
  let raf = null;
  let activeCluster = null;

  /* ── setup ───────────────────────────────────────── */

  function compile(src, type) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }

  function initGL() {
    canvas = $("ws-canvas");
    gl = canvas.getContext("webgl", { alpha: true, antialias: true, premultipliedAlpha: false });
    if (!gl) throw new Error("WebGL unavailable");

    prog = gl.createProgram();
    gl.attachShader(prog, compile(VERT, gl.VERTEX_SHADER));
    gl.attachShader(prog, compile(FRAG, gl.FRAGMENT_SHADER));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    gl.useProgram(prog);

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);   // additive: overlapping points bloom
    gl.disable(gl.DEPTH_TEST);            // additive glow reads better unsorted
  }

  function makeBuffer(points) {
    const n = points.length;
    const pos = new Float32Array(n * 3);
    const col = new Float32Array(n * 3);
    const siz = new Float32Array(n);
    points.forEach((p, i) => {
      pos.set(p.pos, i * 3);
      col.set(p.color, i * 3);
      siz[i] = p.size;
    });
    const mk = (arr) => {
      const b = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, arr, gl.STATIC_DRAW);
      return b;
    };
    return { pos: mk(pos), col: mk(col), siz: mk(siz), count: n };
  }

  function bindAndDraw(buf) {
    if (!buf || !buf.count) return;
    const bind = (b, name, size) => {
      const loc = gl.getAttribLocation(prog, name);
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
    };
    bind(buf.pos, "aPos", 3);
    bind(buf.col, "aColor", 3);
    bind(buf.siz, "aSize", 1);
    gl.drawArrays(gl.POINTS, 0, buf.count);
  }

  /* ── camera + render ─────────────────────────────── */

  function eyePos() {
    return [
      cam.tx + cam.r * Math.cos(cam.el) * Math.sin(cam.az),
      cam.ty + cam.r * Math.sin(cam.el),
      cam.tz + cam.r * Math.cos(cam.el) * Math.cos(cam.az),
    ];
  }

  function mvp() {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const w = canvas.clientWidth * dpr;
    const h = canvas.clientHeight * dpr;
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    gl.viewport(0, 0, canvas.width, canvas.height);
    const proj = perspective(Math.PI / 4, canvas.width / canvas.height, 0.05, 60);
    return mul(proj, lookAt(eyePos(), [cam.tx, cam.ty, cam.tz]));
  }

  function render() {
    // cleared first: if a frame is dropped (background tab stops compositing)
    // the flag must not stay latched, or kick() no-ops forever after
    raf = null;

    // ease toward the target so drags and cluster jumps both feel damped
    let moving = false;
    for (const k of ["az", "el", "r", "tx", "ty", "tz"]) {
      const d = target[k] - cam[k];
      if (Math.abs(d) > 1e-4) {
        cam[k] += d * 0.12;
        moving = true;
      }
    }

    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    const m = mvp();
    gl.useProgram(prog);
    gl.uniformMatrix4fv(gl.getUniformLocation(prog, "uMVP"), false, m);
    gl.uniform1f(gl.getUniformLocation(prog, "uScale"), 2.4 * Math.min(devicePixelRatio || 1, 2));

    if (showSupply) bindAndDraw(buffers.supply);
    bindAndDraw(buffers.demand);
    bindAndDraw(buffers.gap);

    positionLabels(m);
    if (moving) raf = requestAnimationFrame(render);
  }

  function kick() {
    if (!raf) raf = requestAnimationFrame(render);
  }

  /* ── cluster labels (HTML overlay) ───────────────── */

  function projectPoint(m, p) {
    const x = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12];
    const y = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
    const w = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
    if (w <= 0) return null;
    return {
      x: ((x / w) * 0.5 + 0.5) * canvas.clientWidth,
      y: (1 - (y / w * 0.5 + 0.5)) * canvas.clientHeight,
      w,
    };
  }

  function positionLabels(m) {
    const layer = $("ws-labels");
    const W = canvas.clientWidth;
    const H = canvas.clientHeight;
    const placed = [];

    // biggest clusters win the screen space; a 40-post gap matters more than
    // a 5-post one, and 17 labels at once is an unreadable pile
    const order = [...layer.children].sort(
      (a, b) => data.clusters[+b.dataset.i].size - data.clusters[+a.dataset.i].size
    );

    for (const el of order) {
      const c = data.clusters[+el.dataset.i];
      const s = projectPoint(m, c.centroid);
      const active = el.classList.contains("is-active");
      // keep labels fully inside the stage so they never spill over the sidebar
      if (!s || s.x < 70 || s.y < 16 || s.x > W - 70 || s.y > H - 40) {
        el.style.display = "none";
        continue;
      }
      const collides =
        !active && placed.some((p) => Math.abs(p.x - s.x) < 150 && Math.abs(p.y - s.y) < 46);
      if (collides) {
        el.style.display = "none";
        continue;
      }
      placed.push(s);
      el.style.display = "";
      el.style.transform = `translate(-50%, -50%) translate(${s.x}px, ${s.y}px)`;
      el.style.opacity = String(Math.max(0.4, Math.min(1, 2.4 / s.w)));
    }
  }

  /* ── build point buffers ─────────────────────────── */

  function build() {
    const supply = data.supply.map((s) => ({
      pos: s.p,
      color: [0.34, 0.5, 0.92],
      size: 3.0,
    }));

    const gapPts = [];
    const demandPts = [];
    data.demand.forEach((d) => {
      const inCluster = d.c >= 0;
      const pt = {
        pos: d.p,
        // heat by gap score: dim rose -> hot orange
        color: inCluster ? [1.0, 0.45, 0.12] : [0.9, 0.34, 0.4],
        size: inCluster ? 9.0 : 2.8 + d.g * 3.6,
      };
      (inCluster ? gapPts : demandPts).push(pt);
    });

    buffers.supply = makeBuffer(supply);
    buffers.demand = makeBuffer(demandPts);
    buffers.gap = makeBuffer(gapPts);

    const layer = $("ws-labels");
    layer.innerHTML = "";
    data.clusters.forEach((c, i) => {
      const el = document.createElement("button");
      el.className = "ws-label";
      el.dataset.i = String(i);
      el.innerHTML = `<b>${escapeHtml(c.name)}</b><span>${c.size} posts</span>`;
      el.onclick = (e) => {
        e.stopPropagation();
        focusCluster(i);
      };
      layer.append(el);
    });

    $("ws-stats").textContent =
      `${data.stats.supply_count.toLocaleString()} YC companies · ` +
      `${data.stats.demand_count.toLocaleString()} HN demand posts · ` +
      `${data.stats.cluster_count} gap clusters`;

    renderClusterList();
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
  }

  /* ── cluster detail ──────────────────────────────── */

  function renderClusterList() {
    const list = $("ws-cluster-list");
    list.innerHTML = "";
    data.clusters.forEach((c, i) => {
      const b = document.createElement("button");
      b.className = "ws-cluster-item";
      b.innerHTML = `
        <span class="ws-ci-size">${c.size}</span>
        <span class="ws-ci-main">
          <b>${escapeHtml(c.name)}</b>
          <em>gap ${c.avg_gap}</em>
        </span>`;
      b.onclick = () => focusCluster(i);
      list.append(b);
    });
  }

  function focusCluster(i) {
    activeCluster = i;
    const c = data.clusters[i];
    target.tx = c.centroid[0];
    target.ty = c.centroid[1];
    target.tz = c.centroid[2];
    target.r = 1.15;
    kick();

    [...$("ws-labels").children].forEach((el, j) => el.classList.toggle("is-active", j === i));

    const posts = c.posts
      .map(
        (p) => `<li><a href="${escapeHtml(p.u)}" target="_blank" rel="noopener">${escapeHtml(p.t)}</a>
          <span>${p.pts ? `${p.pts} pts · ` : ""}${escapeHtml(p.d || "")}</span></li>`
      )
      .join("");
    const near = c.nearest_yc
      .map((y) => `<li><b>${escapeHtml(y.n)}</b> — ${escapeHtml(y.o)}</li>`)
      .join("");

    $("ws-detail").innerHTML = `
      <button class="ws-detail-close" id="ws-detail-close" aria-label="Close">
        <svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
      <p class="ws-detail-kicker">Gap cluster · ${c.size} posts · avg gap ${c.avg_gap}</p>
      <h3>${escapeHtml(c.name)}</h3>
      ${c.thesis ? `<p class="ws-thesis">${escapeHtml(c.thesis)}</p>` : ""}
      ${c.why_gap ? `<p class="ws-why"><b>Why it's open:</b> ${escapeHtml(c.why_gap)}</p>` : ""}
      <h4>Nearest existing companies</h4>
      <ul class="ws-near">${near}</ul>
      <h4>Real posts in this cluster</h4>
      <ul class="ws-posts">${posts}</ul>`;
    // The map finds the opening; the matcher finds who could build it. Without
    // this the map is a poster — with it, a gap is one click from real people.
    const act = document.createElement("div");
    act.className = "ws-detail-actions";
    act.innerHTML = `
      <button class="btn-primary" id="ws-find"><span>Find researchers for this</span></button>
      <button class="ghost-btn" id="ws-hub">Who else is building here</button>`;
    $("ws-detail").insertBefore(act, $("ws-detail").querySelector("h4"));

    $("ws-find").onclick = () => {
      const seed = `${c.name}. ${c.thesis || ""}`.trim();
      document.getElementById("problem-input").value = seed;
      // A cluster thesis is always a novel query, so this never hits the cache.
      // fromDeck puts the spinner where the results will appear rather than
      // dropping the user back on the landing page mid-search.
      window.runSearch(seed, { fromDeck: true });
    };
    $("ws-hub").onclick = () => {
      window.Hub.open();
      const q = document.getElementById("hub-q");
      q.value = c.name.split(/[\s,]+/).slice(0, 2).join(" ");
      q.dispatchEvent(new Event("input"));
    };

    $("ws-detail").hidden = false;
    $("ws-detail-close").onclick = () => {
      $("ws-detail").hidden = true;
      activeCluster = null;
      [...$("ws-labels").children].forEach((el) => el.classList.remove("is-active"));
    };
  }

  /* ── interaction ─────────────────────────────────── */

  function attachControls() {
    let dragging = false, lx = 0, ly = 0;

    canvas.addEventListener("pointerdown", (e) => {
      dragging = true;
      lx = e.clientX;
      ly = e.clientY;
      canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      target.az -= (e.clientX - lx) * 0.006;
      target.el = Math.max(-1.35, Math.min(1.35, target.el + (e.clientY - ly) * 0.006));
      lx = e.clientX;
      ly = e.clientY;
      kick();
    });
    const stop = () => (dragging = false);
    canvas.addEventListener("pointerup", stop);
    canvas.addEventListener("pointercancel", stop);

    canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        target.r = Math.max(0.35, Math.min(6.5, target.r * (1 + Math.sign(e.deltaY) * 0.12)));
        kick();
      },
      { passive: false }
    );

    $("ws-toggle-supply").onchange = (e) => {
      showSupply = e.target.checked;
      kick();
    };
    $("ws-reset").onclick = () => {
      Object.assign(target, { az: 0.7, el: 0.35, r: 3.1, tx: 0, ty: 0, tz: 0 });
      $("ws-detail").hidden = true;
      activeCluster = null;
      [...$("ws-labels").children].forEach((el) => el.classList.remove("is-active"));
      kick();
    };

    addEventListener("resize", kick);
    // a tab restored from the background needs a repaint to size the canvas
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) kick();
    });
  }

  /* ── boot ────────────────────────────────────────── */

  let booted = false;
  async function boot() {
    if (booted) return;
    booted = true;
    try {
      const res = await fetch("/api/whitespace");
      if (!res.ok) throw new Error(await res.text());
      data = await res.json();
      initGL();
      build();
      attachControls();
      kick();
      $("ws-loading").hidden = true;
    } catch (err) {
      booted = false;
      $("ws-loading").innerHTML = `<p class="ws-err">Map unavailable — run <code>python ingest/whitespace_map.py</code> to build it.</p>`;
      console.error(err);
    }
  }

  window.WhiteSpace = { boot, kick };
})();
