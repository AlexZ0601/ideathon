/* ResearchBridge — swipe UI
   The deck renders three cards deep; only the top one is interactive. */

const $ = (id) => document.getElementById(id);
const VISIBLE = 3;
const THROW = 110;           // px of drag past which release commits the swipe

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
      body: JSON.stringify({ problem, k: 12 }),
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
    toast("Search failed — is the index built?");
    console.error(err);
  } finally {
    btn.disabled = false;
    btn.querySelector("span").textContent = "Find researchers";
  }
});

/* ── deck ────────────────────────────────────────── */

function cardEl(match, rank) {
  const el = document.createElement("article");
  el.className = "card";

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
      ? `You shortlisted ${state.shortlist.length}.`
      : "You passed on everyone — try rephrasing the problem.";
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

/* ── intro modal ─────────────────────────────────── */

let lastEmail = null;

async function openIntro(match) {
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
    $("intro-body").innerHTML = `<p class="loading-note">Couldn't draft the email. Check the API key and try again.</p>`;
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

loadScenarios();
