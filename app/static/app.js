/* Cofoundr — swipe UI
   The deck renders three cards deep; only the top one is interactive. */

const $ = (id) => document.getElementById(id);
const VISIBLE = 3;
const THROW = 110;           // px of drag past which release commits the swipe
const PAGE = 25;             // matches fetched per batch; "load more" asks for another

const state = {
  problem: "",
  matches: [],
  cursor: 0,
  shortlist: [],
};

/* ── view routing ────────────────────────────────── */

function show(viewId) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("is-active", v.id === viewId));
}
window.showView = show;

function toast(msg, ms = 2200) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.hidden = true), ms);
}

/* ── search ──────────────────────────────────────── */

async function loadScenarios() {
  try {
    const { scenarios } = await (await fetch("/api/scenarios")).json();
    $("scenario-chips").innerHTML = "";
    scenarios.forEach((s) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip";
      b.textContent = s.label;
      b.onclick = () => {
        $("problem-input").value = s.text;
        $("problem-input").focus();
      };
      $("scenario-chips").append(b);
    });
  } catch {
    /* chips are a convenience; the app works without them */
  }
}

$("search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const problem = $("problem-input").value.trim();
  if (!problem) return;

  const btn = $("search-btn");
  btn.disabled = true;
  btn.querySelector("span").textContent = "Searching 23,112 abstracts…";

  try {
    const res = await fetch("/api/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ problem, k: PAGE }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    state.problem = problem;
    state.matches = data.matches;
    state.cursor = 0;
    state.shortlist = [];

    $("topbar-problem").textContent = problem;
    updateShortlistCount();
    show("deck-view");
    renderDeck();
  } catch (err) {
    toast(
      err instanceof TypeError
        ? "Can't reach the server — is uvicorn still running?"
        : "Search failed — check the terminal for the error."
    );
    console.error(err);
  } finally {
    btn.disabled = false;
    btn.querySelector("span").textContent = "Find researchers";
  }
});

/* ── deck ────────────────────────────────────────── */

function cardEl(match, rank) {
  const el = document.createElement("article");
  el.className = "card hud";

  const signals = (match.signals || [])
    .map((s) => `<span class="signal${/Established PI/.test(s) ? " is-pi" : ""}">${esc(s)}</span>`)
    .join("");

  el.innerHTML = `
    <div class="stamp keep">Shortlist</div>
    <div class="stamp pass">Pass</div>
    <p class="card-rank">Match ${rank} of ${state.matches.length}</p>
    <h2 class="card-name">${esc(match.name)}</h2>
    <p class="card-dept">${esc(match.dept || "Princeton University")}</p>
    <div class="evidence">
      <p class="evidence-label">Matched on</p>
      <p class="evidence-title">${esc(match.matched_work.title)}
        <span class="evidence-year">(${match.matched_work.year ?? "n.d."})</span></p>
    </div>
    <p class="rationale">${esc(match.rationale || "Semantically closest work in their recent publication record.")}</p>
    <div class="signals">${signals}</div>
  `;
  return el;
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

function renderDeck() {
  const deck = $("deck");
  deck.innerHTML = "";

  const remaining = state.matches.length - state.cursor;
  const done = remaining <= 0;
  $("deck-empty").hidden = !done;
  $("deck-controls").style.visibility = done ? "hidden" : "";
  $("progress").textContent = done ? "" : `${state.cursor + 1} / ${state.matches.length}`;

  if (done) {
    $("deck-empty-sub").textContent = state.shortlist.length
      ? `You shortlisted ${state.shortlist.length} of ${state.matches.length}.`
      : "You passed on all of them — try rephrasing the problem, or pull more.";
    return;
  }

  // back-to-front so the top card is last in the DOM
  const slice = state.matches.slice(state.cursor, state.cursor + VISIBLE).reverse();
  slice.forEach((m, i) => {
    const depth = slice.length - 1 - i;   // 0 = top
    const el = cardEl(m, state.matches.indexOf(m) + 1);
    // offset has to outrun the scale shrink, or the stack hides behind the top card
    el.style.transform = `translateY(${depth * 22}px) scale(${1 - depth * 0.04})`;
    el.style.opacity = depth > 1 ? 0.5 : 1;
    el.style.zIndex = String(10 - depth);
    if (depth === 0) attachDrag(el, m);
    deck.append(el);
  });
}

function attachDrag(el, match) {
  let startX = 0, startY = 0, dx = 0, dy = 0, dragging = false;

  const onDown = (e) => {
    dragging = true;
    // tells the hover-tilt in motion.js to keep its hands off `transform`
    el.dataset.dragging = "1";
    startX = e.clientX;
    startY = e.clientY;
    el.setPointerCapture(e.pointerId);
    el.classList.remove("is-animating");
  };

  const onMove = (e) => {
    if (!dragging) return;
    dx = e.clientX - startX;
    dy = e.clientY - startY;
    el.style.transform = `translate(${dx}px, ${dy}px) rotate(${dx / 22}deg)`;
    const t = Math.min(Math.abs(dx) / THROW, 1);
    el.querySelector(".stamp.keep").style.opacity = dx > 0 ? t : 0;
    el.querySelector(".stamp.pass").style.opacity = dx < 0 ? t : 0;
  };

  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    delete el.dataset.dragging;
    if (Math.abs(dx) > THROW) {
      commit(el, match, dx > 0 ? "keep" : "pass");
    } else {
      el.classList.add("is-animating");
      el.style.transform = "translateY(0) scale(1)";
      el.querySelectorAll(".stamp").forEach((s) => (s.style.opacity = 0));
    }
    dx = dy = 0;
  };

  el.addEventListener("pointerdown", onDown);
  el.addEventListener("pointermove", onMove);
  el.addEventListener("pointerup", onUp);
  el.addEventListener("pointercancel", onUp);
}

function commit(el, match, verdict) {
  if (verdict === "keep") state.shortlist.push(match);
  updateShortlistCount();

  el.classList.add("is-animating");
  const dir = verdict === "keep" ? 1 : -1;
  el.style.transform = `translate(${dir * 620}px, 60px) rotate(${dir * 26}deg)`;
  el.style.opacity = "0";

  state.cursor += 1;
  setTimeout(renderDeck, 260);
}

function swipeTop(verdict) {
  const top = $("deck").lastElementChild;
  if (!top || !top.classList.contains("card")) return;
  commit(top, state.matches[state.cursor], verdict);
}

$("pass-btn").onclick = () => swipeTop("pass");
$("keep-btn").onclick = () => swipeTop("keep");

document.addEventListener("keydown", (e) => {
  if (!$("deck-view").classList.contains("is-active")) return;
  if ($("intro-modal").hidden === false) return;
  if (e.key === "ArrowLeft") swipeTop("pass");
  if (e.key === "ArrowRight") swipeTop("keep");
});

/* ── shortlist ───────────────────────────────────── */

function updateShortlistCount() {
  $("shortlist-count").textContent = String(state.shortlist.length);
}

function renderShortlist() {
  const list = $("shortlist-list");
  list.innerHTML = "";
  if (!state.shortlist.length) {
    list.innerHTML = `<p class="sl-empty">Nothing shortlisted yet. Swipe right on a researcher whose paper looks relevant.</p>`;
    return;
  }
  state.shortlist.forEach((m) => {
    const item = document.createElement("div");
    item.className = "sl-item";
    item.innerHTML = `
      <div class="sl-main">
        <h3 class="sl-name">${esc(m.name)}</h3>
        <p class="sl-dept">${esc(m.dept || "Princeton University")}</p>
        <p class="sl-paper">${esc(m.matched_work.title)}
          <span>(${m.matched_work.year ?? "n.d."})</span></p>
      </div>
    `;
    const btn = document.createElement("button");
    btn.className = "btn-primary";
    btn.textContent = "Draft intro";
    btn.onclick = () => openIntro(m);
    item.append(btn);
    list.append(item);
  });
}

$("shortlist-btn").onclick = () => { renderShortlist(); show("shortlist-view"); };
$("view-shortlist-btn").onclick = () => { renderShortlist(); show("shortlist-view"); };
$("shortlist-back-btn").onclick = () => show("deck-view");
$("back-btn").onclick = () => show("search-view");

/* ── founder profile ─────────────────────────────── */

const PROFILE_FIELDS = ["name", "year", "major", "project"];
const PROFILE_KEY = "rb.founder";

function loadProfile() {
  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(PROFILE_KEY) || "{}");
  } catch {
    /* corrupt entry is not worth failing the page over */
  }
  PROFILE_FIELDS.forEach((f) => {
    const el = $(`f-${f}`);
    if (!el) return;
    if (saved[f]) el.value = saved[f];
    el.addEventListener("input", saveProfile);
  });
}

function saveProfile() {
  const data = {};
  PROFILE_FIELDS.forEach((f) => {
    const v = $(`f-${f}`)?.value.trim();
    if (v) data[f] = v;
  });
  try {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(data));
  } catch {
    /* private browsing — the profile just won't persist */
  }
}

function founderPayload() {
  const data = {};
  PROFILE_FIELDS.forEach((f) => {
    const v = $(`f-${f}`)?.value.trim();
    if (v) data[f] = v;
  });
  // omit entirely when blank so the server's defaults (and the precomputed
  // cache built against them) still apply
  return Object.keys(data).length ? data : undefined;
}

/* ── intro modal ─────────────────────────────────── */

let lastEmail = null;
let lastMatch = null;

async function openIntro(match) {
  lastMatch = match;
  // the market-check and hub-compose flows borrow this modal and hide buttons
  $("copy-btn").hidden = false;
  $("send-btn").hidden = false;
  $("send-btn").querySelector("span").textContent = "Send via cofoundr";
  const modal = $("intro-modal");
  modal.hidden = false;
  $("intro-body").innerHTML = `<div class="spinner"></div><p class="loading-note">Drafting an email that cites ${esc(match.matched_work.title.slice(0, 60))}…</p>`;
  $("intro-hint").textContent = "";
  lastEmail = null;

  try {
    const res = await fetch("/api/intro", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        researcher_id: match.researcher_id,
        work_id: match.matched_work.id,
        problem: state.problem,
        ...(founderPayload() ? { founder: founderPayload() } : {}),
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    const email = await res.json();
    lastEmail = email;

    $("intro-body").innerHTML = `
      <div class="email-field"><b>To</b><span>${esc(email.researcher)}</span></div>
      <div class="email-field"><b>Subject</b><span>${esc(email.subject)}</span></div>
      <div class="email-body">${esc(email.body)}</div>
    `;
    $("intro-hint").textContent = email.to_hint || "";
  } catch (err) {
    // Distinguish "server isn't running" from "the API call failed" — they need
    // different fixes and the old message blamed the key for both.
    const offline = err instanceof TypeError;
    $("intro-body").innerHTML = `<p class="loading-note">${
      offline
        ? "Can't reach the Cofoundr server. Is <code>uvicorn</code> still running in your terminal?"
        : `The draft request failed: ${esc(String(err.message || err).slice(0, 200))}`
    }</p>`;
    console.error(err);
  }
}

$("intro-close").onclick = () => ($("intro-modal").hidden = true);
$("intro-modal").addEventListener("click", (e) => {
  if (e.target === $("intro-modal")) $("intro-modal").hidden = true;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("intro-modal").hidden = true;
});

$("copy-btn").onclick = async () => {
  if (!lastEmail) return;
  try {
    await navigator.clipboard.writeText(`Subject: ${lastEmail.subject}\n\n${lastEmail.body}`);
    toast("Email copied to clipboard");
  } catch {
    toast("Copy failed — select the text manually");
  }
};

$("send-btn").onclick = async () => {
  if (!lastEmail || !lastMatch) return;
  const btn = $("send-btn");
  btn.disabled = true;
  try {
    const res = await window.Accounts.sendIntro({
      researcher_id: lastMatch.researcher_id,
      subject: lastEmail.subject,
      body: lastEmail.body,
      paper_title: lastMatch.matched_work.title,
    });
    // null means the user was bounced to sign-up; the send resumes after auth
    if (res) {
      $("intro-modal").hidden = true;
      toast(res.notice, 6000);
    }
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
};

/* ── white space map ─────────────────────────────── */

const openMap = () => {
  show("ws-view");
  window.WhiteSpace.boot();
  requestAnimationFrame(() => window.WhiteSpace.kick());
};
$("open-map").onclick = openMap;
$("open-map-2").onclick = openMap;
$("open-hub").onclick = () => window.Hub.open();
$("open-dir").onclick = () => window.Directory.open();

/* Market check: the same problem text, run against the White Space corpora.
   Tells a founder whether the thing they're already building sits in open
   territory or in a crowd of funded companies. */
$("position-btn").onclick = async () => {
  if (!state.problem) return;
  const modal = $("intro-modal");
  modal.hidden = false;
  $("copy-btn").hidden = true;
  $("send-btn").hidden = true;
  $("intro-hint").textContent = "";
  $("intro-body").innerHTML = `<div class="spinner"></div><p class="loading-note">Placing this against 6,049 funded companies…</p>`;

  try {
    const res = await fetch("/api/whitespace/position", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ problem: state.problem }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail);

    const bar = (v, label) => `
      <div class="meter">
        <div class="meter-head"><span>${label}</span><b>${v.toFixed(2)}</b></div>
        <div class="meter-track"><div class="meter-fill" style="width:${Math.min(v / 0.6, 1) * 100}%"></div></div>
      </div>`;

    $("intro-body").innerHTML = `
      <p class="ws-detail-kicker">Market check</p>
      <h3 class="pos-verdict">${esc(d.verdict)}</h3>
      ${bar(d.crowding, "How close funded companies sit")}
      ${bar(d.demand_pull, "How loudly people are asking")}
      <h4>Closest funded companies</h4>
      <ul class="ws-near">
        ${d.nearest_companies.map((c) => `<li><b>${esc(c.name)}</b>${c.batch ? ` <em>(${esc(c.batch)})</em>` : ""} — ${esc(c.one_liner)}</li>`).join("")}
      </ul>
      <h4>People describing this problem</h4>
      <ul class="ws-posts">
        ${d.nearest_demand.map((p) => `<li><a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a></li>`).join("")}
      </ul>`;
    $("intro-hint").textContent =
      "Embedding distance, not market research. A crowded score means someone " +
      "funded is semantically near — not that they've won.";
  } catch (e) {
    $("intro-body").innerHTML = `<p class="loading-note">${esc(e.message || "Market check failed.")}</p>`;
  }
};

// Pull the next batch. match() is deterministic and ordered, so asking for a
// bigger k returns the same head plus a longer tail — we append only the tail.
$("load-more-btn").onclick = async () => {
  const btn = $("load-more-btn");
  btn.disabled = true;
  btn.textContent = "Searching…";
  try {
    const res = await fetch("/api/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ problem: state.problem, k: state.matches.length + PAGE }),
    });
    const data = await res.json();
    const fresh = data.matches.slice(state.matches.length);
    if (!fresh.length) {
      btn.textContent = "No more matches";
      return;
    }
    state.matches = state.matches.concat(fresh);
    renderDeck();
  } catch {
    toast("Couldn't load more — is the server still running?");
  } finally {
    btn.disabled = false;
    if (btn.textContent === "Searching…") btn.textContent = `Load ${PAGE} more`;
  }
};
// hub.js needs the toast without importing this module
window.toastMsg = toast;
$("ws-back").onclick = () => show("search-view");

loadScenarios();
loadProfile();
