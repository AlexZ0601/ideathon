/* Flowing mesh-gradient backdrop, in the spirit of ShaderGradient.

   ShaderGradient itself is React + three.js + react-three-fiber; this app is
   vanilla with no bundler, and the demo has to run with wifi off. So this is
   the technique rather than the package: one fullscreen fragment shader with
   domain-warped fBm noise, mixing between the theme's own colours.

   Costs one draw call. Rendered at a capped resolution because the output is
   a soft gradient — nobody can see the missing pixels, and a fullscreen
   fragment shader at DPR 2 on a retina display is genuinely expensive. */

(() => {
  const VERT = `
    attribute vec2 aPos;
    void main() { gl_Position = vec4(aPos, 0.0, 1.0); }`;

  const FRAG = `
    precision highp float;
    uniform vec2  uRes;
    uniform float uTime;
    uniform vec3  uC1, uC2, uC3, uBg;
    uniform float uStrength;
    uniform vec2  uMouse;

    // value noise + fBm. Cheap, and at this blur nobody can tell it from simplex.
    float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

    float noise(vec2 p) {
      vec2 i = floor(p), f = fract(p);
      vec2 u = f * f * (3.0 - 2.0 * f);
      return mix(mix(hash(i), hash(i + vec2(1,0)), u.x),
                 mix(hash(i + vec2(0,1)), hash(i + vec2(1,1)), u.x), u.y);
    }

    float fbm(vec2 p) {
      float v = 0.0, a = 0.5;
      for (int i = 0; i < 5; i++) { v += a * noise(p); p *= 2.02; a *= 0.5; }
      return v;
    }

    void main() {
      vec2 uv = gl_FragCoord.xy / uRes;
      vec2 p = uv * 2.6;
      p.x *= uRes.x / uRes.y;

      float t = uTime * 0.045;

      // domain warp: noise whose input is itself noise. This is what turns
      // flat blobs into something that reads as liquid.
      vec2 q = vec2(fbm(p + vec2(0.0, t)), fbm(p + vec2(5.2, 1.3 - t)));
      vec2 r = vec2(fbm(p + 3.4 * q + vec2(1.7, 9.2) + 0.35 * t),
                    fbm(p + 3.4 * q + vec2(8.3, 2.8) - 0.28 * t));
      float f = fbm(p + 3.6 * r);

      vec3 col = mix(uC1, uC2, clamp(f * 1.9, 0.0, 1.0));
      col = mix(col, uC3, clamp(length(r) * 0.85, 0.0, 1.0));

      // fBm averages ~0.48, so a window starting above that leaves most of the
      // field dark and the effect invisible. This one straddles the mean.
      float mask = smoothstep(0.12, 0.72, f) * uStrength;

      // Aurora bands: the warp field sliced into ridges. This is what reads as
      // motion from across a room — a smooth blob does not.
      float band = abs(sin((r.x + r.y) * 3.4 + uTime * 0.22));
      mask *= 0.55 + 0.45 * (1.0 - band);

      // Light pools away from the hero copy (upper-left) so contrast survives.
      float glowA = smoothstep(1.25, 0.02, distance(uv, vec2(0.88, 0.82)));
      float glowB = smoothstep(1.10, 0.06, distance(uv, vec2(0.04, 0.10))) * 0.8;

      // The cursor drags a soft light with it. Cheap, and it makes the page
      // feel responsive before the user has clicked anything.
      float glowM = smoothstep(0.5, 0.0, distance(uv, uMouse)) * 0.6;

      mask *= clamp(glowA + glowB + glowM, 0.0, 1.0);

      vec3 outc = mix(uBg, col, clamp(mask, 0.0, 1.0));
      // vignette keeps the eye in the middle where the content is
      outc *= 1.0 - 0.22 * smoothstep(0.55, 1.25, distance(uv, vec2(0.5)));
      gl_FragColor = vec4(outc, 1.0);
    }`;

  const canvas = document.createElement("canvas");
  canvas.id = "gradient-bg";
  const gl = canvas.getContext("webgl", { antialias: false, alpha: false });
  if (!gl) return;                    // no WebGL: the CSS gradients still stand
  document.body.prepend(canvas);

  const compile = (src, type) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      console.error(gl.getShaderInfoLog(s));
      return null;
    }
    return s;
  };

  const vs = compile(VERT, gl.VERTEX_SHADER);
  const fs = compile(FRAG, gl.FRAGMENT_SHADER);
  if (!vs || !fs) return canvas.remove();

  const prog = gl.createProgram();
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  gl.useProgram(prog);

  // one big triangle covers the viewport with no seam down the diagonal
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, "aPos");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

  const U = {};
  ["uRes", "uTime", "uC1", "uC2", "uC3", "uBg", "uStrength", "uMouse"].forEach(
    (n) => (U[n] = gl.getUniformLocation(prog, n))
  );

  // eased toward the pointer so the light trails rather than snapping
  const mouse = { x: 0.85, y: 0.8, tx: 0.85, ty: 0.8 };
  addEventListener(
    "pointermove",
    (e) => {
      mouse.tx = e.clientX / innerWidth;
      mouse.ty = 1 - e.clientY / innerHeight;  // GL origin is bottom-left
      kick();
    },
    { passive: true }
  );

  /* ── theme colours, read from the stylesheet ─────── */

  const parse = (css) => {
    const c = css.trim();
    if (c.startsWith("#")) {
      const h = c.length === 4
        ? c.slice(1).split("").map((x) => x + x).join("")
        : c.slice(1, 7);
      const n = parseInt(h, 16);
      return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255];
    }
    const m = c.match(/[\d.]+/g);
    return m ? [m[0] / 255, m[1] / 255, m[2] / 255] : [0, 0, 0];
  };

  let strength = 0.5;

  function readTheme() {
    const s = getComputedStyle(document.documentElement);
    const v = (n) => parse(s.getPropertyValue(n));
    const bg = v("--bg");
    const dark = bg[0] + bg[1] + bg[2] < 1.2;

    gl.useProgram(prog);
    gl.uniform3fv(U.uBg, bg);
    gl.uniform3fv(U.uC1, v("--accent"));
    // second and third stops are hand-picked rather than theme vars: the
    // palette has no cool tones, and a one-hue gradient reads as a smudge
    gl.uniform3fv(U.uC2, dark ? [0.29, 0.36, 0.85] : [0.42, 0.52, 0.95]);
    gl.uniform3fv(U.uC3, dark ? [0.85, 0.25, 0.42] : [0.96, 0.55, 0.35]);
    // light mode washes out fast, so it gets a lighter touch
    // Tuned down hard after the transparent-body fix: with nothing muting it,
    // 1.55 turned the page into a magenta wash you couldn't read over.
    strength = dark ? 0.42 : 0.22;
    gl.uniform1f(U.uStrength, strength);
  }

  /* ── loop ────────────────────────────────────────── */

  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let raf = null;
  let t0 = performance.now();

  function resize() {
    // capped hard: this is a blurry backdrop, resolution buys nothing
    const dpr = Math.min(devicePixelRatio || 1, 1.25);
    const w = Math.round(innerWidth * dpr);
    const h = Math.round(innerHeight * dpr);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      gl.viewport(0, 0, w, h);
      gl.useProgram(prog);
      gl.uniform2f(U.uRes, w, h);
    }
  }

  function frame(now) {
    raf = null;
    resize();
    mouse.x += (mouse.tx - mouse.x) * 0.06;
    mouse.y += (mouse.ty - mouse.y) * 0.06;
    gl.useProgram(prog);
    gl.uniform1f(U.uTime, (now - t0) / 1000);
    gl.uniform2f(U.uMouse, mouse.x, mouse.y);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    if (!reduced.matches && !document.hidden) raf = requestAnimationFrame(frame);
  }

  function kick() {
    if (!raf) raf = requestAnimationFrame(frame);
  }

  readTheme();
  kick();

  addEventListener("resize", kick);
  // a backgrounded tab stops firing rAF; without this the canvas stays frozen
  document.addEventListener("visibilitychange", () => !document.hidden && kick());
  reduced.addEventListener?.("change", kick);

  // the theme switcher re-reads colours through this
  window.GradientBG = {
    refresh() {
      readTheme();
      kick();
    },
  };
})();
