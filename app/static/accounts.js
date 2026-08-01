/* Accounts, profiles, claiming, and the message inbox.

   The one rule this file encodes: a researcher account never *creates* a
   researcher. Every one of the 4,159 already exists from public data. Signing
   up as a researcher means finding yourself and claiming what's there — which
   is why the flow is a search box, not a profile form. */

(() => {
  const $ = (id) => document.getElementById(id);

  const A = {
    user: null,
    box: "inbox",
    messages: { inbox: [], sent: [] },
    afterAuth: null,   // callback to resume whatever the user was doing
  };
  window.Accounts = A;

  const esc = (s) => {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
  };

  const when = (ts) => {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    const days = (Date.now() - d) / 86400000;
    return days < 1
      ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      : d.toLocaleDateString([], { month: "short", day: "numeric" });
  };

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: opts.body instanceof FormData ? {} : { "Content-Type": "application/json" },
      ...opts,
    });
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = { detail: text };
    }
    if (!res.ok) throw new Error(data?.detail || `Request failed (${res.status})`);
    return data;
  }

  /* ── session ─────────────────────────────────────── */

  async function refresh() {
    try {
      const { user } = await api("/api/me");
      A.user = user;
    } catch {
      A.user = null;
    }
    paintNav();
    return A.user;
  }

  function paintNav() {
    const btn = $("nav-account");
    if (!btn) return;
    if (!A.user) {
      btn.textContent = "Sign in";
      btn.classList.remove("has-unread");
      return;
    }
    const first = A.user.name.split(/\s+/)[0];
    btn.textContent = A.user.unread ? `${first} (${A.user.unread})` : first;
    btn.classList.toggle("has-unread", A.user.unread > 0);
    const badge = $("msg-badge");
    if (badge) badge.textContent = String(A.user.unread || 0);
  }

  /* ── intake questions ────────────────────────────── */

  let OPTIONS = { identities: [], seeking: [] };
  const intake = { identity: null, seeking: new Set() };

  async function loadOptions() {
    try {
      OPTIONS = await api("/api/options");
    } catch {
      return;
    }
    const idBox = $("identity-pills");
    idBox.innerHTML = "";
    OPTIONS.identities.forEach((o) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "pill";
      b.textContent = o.label;
      b.onclick = () => {
        intake.identity = o.id;
        [...idBox.children].forEach((c) => c.classList.toggle("is-on", c === b));
        // a researcher signing up is almost never here to find a professor
        if (o.id === "researcher" && !intake.seeking.size) {
          document.querySelector('input[name="role"][value="researcher"]').checked = true;
        }
      };
      idBox.append(b);
    });

    const seekBox = $("seeking-pills");
    seekBox.innerHTML = "";
    OPTIONS.seeking.forEach((o) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "pill";
      b.textContent = o.label;
      b.onclick = () => {
        intake.seeking.has(o.id) ? intake.seeking.delete(o.id) : intake.seeking.add(o.id);
        b.classList.toggle("is-on", intake.seeking.has(o.id));
        paintSeekingHint();
      };
      seekBox.append(b);
    });
  }

  // Tell the user what their answer actually does, rather than collecting it
  // and quietly changing the ranking behind their back.
  function paintSeekingHint() {
    const s = [...intake.seeking];
    const senior = s.filter((x) => ["professor", "researcher", "advisor"].includes(x)).length;
    const junior = s.filter((x) => ["cofounder", "employee"].includes(x)).length;
    const hint = $("seeking-hint");
    if (!s.length) return (hint.textContent = "");
    if (senior && !junior)
      hint.textContent = "We'll rank established PIs higher — people who run labs and take students.";
    else if (junior && !senior)
      hint.textContent =
        "We'll rank early-career people higher — grad students and postdocs are the ones who actually leave to build something.";
    else hint.textContent = "We'll rank on relevance alone, without favouring seniority either way.";
  }

  /* ── auth modal ──────────────────────────────────── */

  let mode = "login";

  function openAuth(nextMode = "login", after = null) {
    mode = nextMode;
    A.afterAuth = after;
    setMode(mode);
    $("auth-error").hidden = true;
    $("auth-modal").hidden = false;
    $("auth-email").focus();
  }

  function setMode(next) {
    mode = next;
    const signup = mode === "signup";
    $("auth-title").textContent = signup ? "Create account" : "Sign in";
    $("auth-submit").querySelector("span").textContent = signup ? "Create account" : "Sign in";
    $("auth-name-field").hidden = !signup;
    $("auth-roles").hidden = !signup;
    $("intake-block").hidden = !signup;
    $("terms-check").hidden = !signup;
    $("auth-password").autocomplete = signup ? "new-password" : "current-password";
    document.querySelectorAll(".auth-mode .seg-btn").forEach((b) =>
      b.classList.toggle("is-on", b.dataset.mode === mode)
    );
  }

  document.querySelectorAll(".auth-mode .seg-btn").forEach((b) => {
    b.onclick = () => setMode(b.dataset.mode);
  });
  $("auth-close").onclick = () => ($("auth-modal").hidden = true);
  $("auth-modal").addEventListener("click", (e) => {
    if (e.target === $("auth-modal")) $("auth-modal").hidden = true;
  });

  $("auth-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("auth-error");
    err.hidden = true;
    const btn = $("auth-submit");
    btn.disabled = true;

    const email = $("auth-email").value.trim();
    const password = $("auth-password").value;
    const role = document.querySelector('input[name="role"]:checked')?.value || "founder";

    try {
      if (mode === "signup") {
        A.user = await api("/api/auth/signup", {
          method: "POST",
          body: JSON.stringify({
            email,
            password,
            name: $("auth-name").value.trim(),
            role,
            identity: intake.identity,
            seeking: [...intake.seeking],
            accept_terms: $("accept-terms").checked,
          }),
        });
      } else {
        A.user = await api("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({ email, password }),
        });
      }
      $("auth-modal").hidden = true;
      $("auth-password").value = "";
      paintNav();
      const after = A.afterAuth;
      A.afterAuth = null;
      if (after) after();
      else openAccount();
    } catch (ex) {
      err.textContent = ex.message;
      err.hidden = false;
    } finally {
      btn.disabled = false;
    }
  });

  /* ── account view ────────────────────────────────── */

  function openAccount() {
    if (!A.user) return openAuth("login", openAccount);
    window.showView("account-view");
    $("account-title").textContent =
      A.user.role === "founder" ? "Your profile" : "Your researcher profile";
    A.user.role === "founder" ? paintFounder() : paintResearcher();
  }

  function paintFounder() {
    const p = A.user.profile || {};
    $("account-body").innerHTML = `
      <div class="pane-inner">
        <div class="acct-head">
          <div>
            <h2>${esc(A.user.name)}</h2>
            <p class="acct-email">${esc(A.user.email)}</p>
          </div>
          <button class="ghost-btn" id="signout">Sign out</button>
        </div>

        <section class="card-block">
          <h3>About you</h3>
          <p class="block-note">Used to draft intro emails in your voice instead of "a Princeton undergraduate".</p>
          <div class="profile-grid">
            <label>Year<input id="p-year" value="${esc(p.year || "")}" placeholder="junior"></label>
            <label>Major<input id="p-major" value="${esc(p.major || "")}" placeholder="Chemical & Biological Engineering"></label>
            <label class="wide">What you're building<input id="p-project" value="${esc(p.project || "")}" placeholder="a low-cost water testing kit for rural clinics"></label>
            <label class="wide">Short bio<textarea id="p-bio" rows="3" placeholder="Anything a professor should know in one line.">${esc(p.bio || "")}</textarea></label>
            <label>School<input id="p-school" value="${esc(p.school || "")}" placeholder="Princeton University"></label>
            <label>Student org<input id="p-org" value="${esc(p.org || "")}" placeholder="Princeton Student Ventures"></label>
            <label>Stage
              <select id="p-stage">
                ${["", "idea", "prototype", "early users", "raising"]
                  .map((s) => `<option value="${s}" ${p.stage === s ? "selected" : ""}>${s || "—"}</option>`)
                  .join("")}
              </select>
            </label>
            <label>Commitment
              <select id="p-commitment">
                ${["", "nights & weekends", "part-time", "full-time"]
                  .map((s) => `<option value="${s}" ${p.commitment === s ? "selected" : ""}>${s || "—"}</option>`)
                  .join("")}
              </select>
            </label>
            <label class="wide">Skills<input id="p-skills" value="${esc(p.skills || "")}" placeholder="Python, microfluidics, assay design"></label>
            <label>Website<input id="p-website" value="${esc(p.website || "")}" placeholder="alexzeng.dev"></label>
            <label>GitHub<input id="p-github" value="${esc(p.github || "")}" placeholder="AlexZ0601"></label>
            <label>LinkedIn<input id="p-linkedin" value="${esc(p.linkedin || "")}" placeholder="in/alexzeng"></label>
          </div>
          <label class="toggle-row">
            <input type="checkbox" id="p-looking" ${p.looking === 0 ? "" : "checked"}>
            <span>List me in the Cofounder Hub</span>
          </label>
          <p class="block-note" style="margin:0">
            Your name, school, org, and what you're building become visible to other
            signed-in members. Your email and resume never are.
          </p>
          <div class="row-end">
            <span class="save-state" id="save-state"></span>
            <button class="btn-primary" id="save-profile"><span>Save profile</span></button>
          </div>
        </section>

        <section class="card-block">
          <h3>Resume</h3>
          <p class="block-note">
            PDF or plain text. We pull the text out and let the email drafter cite one real thing
            from it — a course, a project — when it's genuinely relevant. It is never uploaded anywhere else.
          </p>
          <div class="resume-row">
            <label class="file-btn">
              <input type="file" id="resume-file" accept=".pdf,.txt,.md" hidden>
              <span>Choose file</span>
            </label>
            <p class="resume-state" id="resume-state">${
              p.resume_name
                ? `<b>${esc(p.resume_name)}</b> — ${p.resume_chars.toLocaleString()} characters read`
                : "No resume uploaded yet."
            }</p>
          </div>
        </section>
      </div>`;

    $("account-body").querySelector(".pane-inner").insertAdjacentHTML("beforeend", settingsHTML());
    $("signout").onclick = signOut;
    $("save-profile").onclick = saveProfile;
    $("resume-file").onchange = uploadResume;
    wireSettings();
  }

  /* ── account settings ────────────────────────────── */

  function settingsHTML() {
    return `
      <section class="card-block">
        <h3>Account</h3>
        <p class="block-note">Change your password, take your data with you, or leave.</p>

        <div class="profile-grid">
          <label>Current password<input type="password" id="pw-old" autocomplete="current-password"></label>
          <label>New password<input type="password" id="pw-new" autocomplete="new-password" placeholder="at least 8 characters"></label>
        </div>
        <div class="row-end">
          <span class="save-state" id="pw-state"></span>
          <button class="ghost-btn" id="pw-save">Change password</button>
        </div>

        <div class="settings-row">
          <div>
            <b>Export your data</b>
            <p class="block-note" style="margin:2px 0 0">Everything we hold on you, as JSON.</p>
          </div>
          <button class="ghost-btn" id="export-btn">Download</button>
        </div>

        <div class="settings-row danger">
          <div>
            <b>Delete account</b>
            <p class="block-note" style="margin:2px 0 0">
              Permanent. Removes your profile, resume, and the messages you sent.
            </p>
          </div>
          <button class="ghost-btn danger-btn" id="del-open">Delete…</button>
        </div>
        <div class="danger-confirm" id="del-confirm" hidden>
          <p>Type <b>DELETE</b> to confirm. This cannot be undone.</p>
          <div class="row-end" style="justify-content:flex-start;gap:10px">
            <input id="del-input" placeholder="DELETE" autocomplete="off">
            <button class="ghost-btn danger-btn" id="del-go">Delete permanently</button>
            <button class="ghost-btn" id="del-cancel">Cancel</button>
          </div>
          <p class="save-state" id="del-state"></p>
        </div>
      </section>`;
  }

  function wireSettings() {
    $("pw-save").onclick = async () => {
      const st = $("pw-state");
      st.textContent = "Saving…";
      try {
        await api("/api/account/password", {
          method: "POST",
          body: JSON.stringify({
            current: $("pw-old").value,
            new_password: $("pw-new").value,
          }),
        });
        st.textContent = "Password changed.";
        $("pw-old").value = $("pw-new").value = "";
      } catch (e) {
        st.textContent = e.message;
      }
    };

    $("export-btn").onclick = async () => {
      const data = await api("/api/account/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "cofoundr-export.json";
      a.click();
      URL.revokeObjectURL(a.href);
    };

    $("del-open").onclick = () => ($("del-confirm").hidden = false);
    $("del-cancel").onclick = () => ($("del-confirm").hidden = true);
    $("del-go").onclick = async () => {
      const st = $("del-state");
      try {
        await api("/api/account/delete", {
          method: "POST",
          body: JSON.stringify({ confirm: $("del-input").value }),
        });
        A.user = null;
        paintNav();
        window.showView("search-view");
      } catch (e) {
        st.textContent = e.message;
      }
    };
  }

  async function saveProfile() {
    const state = $("save-state");
    state.textContent = "Saving…";
    try {
      A.user = await api("/api/profile", {
        method: "PUT",
        body: JSON.stringify({
          year: $("p-year").value.trim(),
          major: $("p-major").value.trim(),
          project: $("p-project").value.trim(),
          bio: $("p-bio").value.trim(),
          school: $("p-school").value.trim(),
          org: $("p-org").value.trim(),
          looking: $("p-looking").checked,
          stage: $("p-stage").value,
          commitment: $("p-commitment").value,
          skills: $("p-skills").value.trim(),
          website: $("p-website").value.trim(),
          github: $("p-github").value.trim(),
          linkedin: $("p-linkedin").value.trim(),
        }),
      });
      state.textContent = "Saved.";
      setTimeout(() => (state.textContent = ""), 2200);
    } catch (e) {
      state.textContent = e.message;
    }
  }

  async function uploadResume(e) {
    const file = e.target.files[0];
    if (!file) return;
    const state = $("resume-state");
    state.textContent = "Reading…";
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api("/api/resume", { method: "POST", body: fd });
      state.innerHTML = `<b>${esc(r.resume_name)}</b> — ${r.resume_chars.toLocaleString()} characters read`;
      await refresh();
    } catch (ex) {
      state.textContent = ex.message;
    }
  }

  /* ── researcher: claim, don't create ─────────────── */

  function paintResearcher() {
    const claim = A.user.claim;
    $("account-body").innerHTML = `
      <div class="pane-inner">
        <div class="acct-head">
          <div>
            <h2>${esc(A.user.name)}</h2>
            <p class="acct-email">${esc(A.user.email)}</p>
          </div>
          <button class="ghost-btn" id="signout">Sign out</button>
        </div>

        ${
          claim
            ? `<section class="card-block claimed">
                 <p class="kicker">Claimed profile</p>
                 <h3>${esc(claim.name || "")}</h3>
                 <p class="block-note">${esc(claim.dept || "")} · ${claim.works} recent papers indexed</p>
                 <label class="toggle-row">
                   <input type="checkbox" id="accepting" ${claim.accepting ? "checked" : ""}>
                   <span>Open to student intros right now</span>
                 </label>
                 <p class="block-note">
                   Turning this off doesn't hide your published work — that was always public.
                   It just tells students not to expect a reply.
                 </p>
               </section>`
            : `<section class="card-block">
                 <h3>Find yourself</h3>
                 <p class="block-note">
                   You already have a profile here. We built it from your public OpenAlex record
                   before you ever visited — nothing to fill in. Search your name to claim it.
                 </p>
                 <input class="claim-search" id="claim-q" placeholder="Type your last name…" autocomplete="off">
                 <div class="claim-results" id="claim-results"></div>
               </section>`
        }
      </div>`;

    $("signout").onclick = signOut;
    if (claim) {
      $("accepting").onchange = async (e) => {
        A.user = await api("/api/claim/accepting", {
          method: "PUT",
          body: JSON.stringify({ accepting: e.target.checked }),
        });
      };
    } else {
      let timer;
      $("claim-q").oninput = (e) => {
        clearTimeout(timer);
        timer = setTimeout(() => searchClaim(e.target.value), 220);
      };
    }
  }

  async function searchClaim(q) {
    const box = $("claim-results");
    if (q.trim().length < 2) return (box.innerHTML = "");
    const { results } = await api(`/api/researchers/search?q=${encodeURIComponent(q)}`);
    if (!results.length) {
      box.innerHTML = `<p class="block-note">No match. Only researchers with 3+ papers since 2021 are indexed.</p>`;
      return;
    }
    box.innerHTML = results
      .map(
        (r, i) => `
        <div class="claim-item">
          <div class="claim-main">
            <b>${esc(r.name)}</b>
            <span>${esc(r.dept || "")} · ${r.works} recent papers</span>
            <em>${esc(r.recent[0] || "")}</em>
            ${r.pending ? `<span class="pending-flag">${r.pending} message${r.pending > 1 ? "s" : ""} waiting</span>` : ""}
          </div>
          ${
            r.claimed
              ? `<span class="claimed-flag">Already claimed</span>`
              : `<button class="btn-primary" data-claim="${esc(r.researcher_id)}"><span>This is me</span></button>`
          }
        </div>`
      )
      .join("");
    box.querySelectorAll("[data-claim]").forEach((b) => {
      b.onclick = async () => {
        b.disabled = true;
        try {
          A.user = await api("/api/claim", {
            method: "POST",
            body: JSON.stringify({ researcher_id: b.dataset.claim }),
          });
          paintResearcher();
          await refresh();
        } catch (e) {
          b.disabled = false;
          alert(e.message);
        }
      };
    });
  }

  async function signOut() {
    await api("/api/auth/logout", { method: "POST" });
    A.user = null;
    paintNav();
    window.showView("search-view");
  }

  /* ── messages ────────────────────────────────────── */

  async function openMessages() {
    if (!A.user) return openAuth("login", openMessages);
    window.showView("messages-view");
    A.messages = await api("/api/messages");
    await refresh();
    paintList();
    $("msg-thread").innerHTML = `<p class="thread-empty">Pick a conversation.</p>`;
  }

  function paintList() {
    const items = A.messages[A.box] || [];
    const list = $("msg-list");
    if (!items.length) {
      list.innerHTML = `<p class="thread-empty">${
        A.box === "inbox" ? "No messages yet." : "You haven't sent anything yet."
      }</p>`;
      return;
    }
    // one row per thread, newest first
    const seen = new Set();
    list.innerHTML = items
      .filter((m) => !seen.has(m.thread_id) && seen.add(m.thread_id))
      .map(
        (m) => `
        <button class="msg-item ${m.read_at || A.box === "sent" ? "" : "is-unread"}" data-thread="${m.thread_id}">
          <span class="msg-who">${esc(
            A.box === "inbox" ? m.from_name : m.to_name || "Not on Cofoundr yet"
          )}</span>
          <span class="msg-subject">${esc(m.subject)}</span>
          <span class="msg-preview">${esc((m.body || "").slice(0, 90))}</span>
          <span class="msg-when">${when(m.created_at)}</span>
        </button>`
      )
      .join("");
    list.querySelectorAll("[data-thread]").forEach((b) => {
      b.onclick = () => openThread(+b.dataset.thread);
    });
  }

  async function openThread(tid) {
    const { messages } = await api(`/api/messages/${tid}`);
    // The translate action is for whoever is *receiving* founder-speak, so it
    // only appears on a message someone else wrote.
    const incoming = messages.find((m) => m.from_user !== A.user.id);
    $("msg-thread").innerHTML = `
      <div class="thread-head">
        <h3>${esc(messages[0].subject)}</h3>
        ${messages[0].paper_title ? `<p class="thread-paper">Re: ${esc(messages[0].paper_title)}</p>` : ""}
        ${
          incoming
            ? `<button class="ghost-btn plain-btn" id="plain-btn">Translate the jargon</button>
               <div class="plain-out" id="plain-out" hidden></div>`
            : ""
        }
      </div>
      <div class="thread-msgs">
        ${messages
          .map(
            (m) => `<div class="bubble ${m.from_user === A.user.id ? "mine" : ""}">
              <p class="bubble-who">${esc(m.from_name)} · ${when(m.created_at)}</p>
              <p class="bubble-body">${esc(m.body)}</p>
            </div>`
          )
          .join("")}
      </div>
      <form class="reply-form" id="reply-form">
        <textarea id="reply-body" rows="3" placeholder="Write a reply…"></textarea>
        <button class="btn-primary" type="submit"><span>Send reply</span></button>
      </form>`;
    if (incoming) {
      $("plain-btn").onclick = async () => {
        const btn = $("plain-btn");
        const out = $("plain-out");
        btn.disabled = true;
        btn.textContent = "Translating…";
        out.hidden = false;
        out.innerHTML = `<div class="spinner"></div>`;
        try {
          const t = await A.translate(incoming.body, incoming.subject);
          out.innerHTML = `
            <p class="plain-kicker">In plain English</p>
            <p class="plain-body">${esc(t.plain)}</p>
            ${t.ask ? `<p class="plain-ask"><b>What they want:</b> ${esc(t.ask)}${
              t.time_ask ? ` (${esc(t.time_ask)})` : ""
            }</p>` : ""}
            ${
              t.glossary.length
                ? `<dl class="glossary">${t.glossary
                    .map((g) => `<dt>${esc(g.term)}</dt><dd>${esc(g.meaning)}</dd>`)
                    .join("")}</dl>`
                : `<p class="plain-none">No startup jargon to unpack — the message was already plain.</p>`
            }`;
        } catch (e) {
          out.innerHTML = `<p class="plain-none">${esc(e.message)}</p>`;
        } finally {
          btn.disabled = false;
          btn.textContent = "Translate the jargon";
        }
      };
    }

    $("reply-form").onsubmit = async (e) => {
      e.preventDefault();
      const body = $("reply-body").value.trim();
      if (!body) return;
      await api("/api/messages", { method: "POST", body: JSON.stringify({ thread_id: tid, body }) });
      A.messages = await api("/api/messages");
      openThread(tid);
      paintList();
    };
    A.messages = await api("/api/messages");
    await refresh();
    paintList();
  }

  document.querySelectorAll("#msg-tabs .seg-btn").forEach((b) => {
    b.onclick = () => {
      A.box = b.dataset.box;
      document.querySelectorAll("#msg-tabs .seg-btn").forEach((x) =>
        x.classList.toggle("is-on", x === b)
      );
      paintList();
      $("msg-thread").innerHTML = `<p class="thread-empty">Pick a conversation.</p>`;
    };
  });

  /* ── send an intro through the app ───────────────── */

  A.sendIntro = async ({ researcher_id, subject, body, paper_title }) => {
    if (!A.user) {
      openAuth("signup", () => A.sendIntro({ researcher_id, subject, body, paper_title }));
      return null;
    }
    return api("/api/messages", {
      method: "POST",
      body: JSON.stringify({ researcher_id, subject, body, paper_title }),
    });
  };

  /* ── terms ───────────────────────────────────────── */

  let termsLoaded = false;
  async function openTerms() {
    window.showView("terms-view");
    if (termsLoaded) return;
    try {
      const res = await fetch("/api/terms");
      $("terms-body").innerHTML = `<div class="pane-inner">${await res.text()}</div>`;
      termsLoaded = true;
    } catch {
      $("terms-body").innerHTML = `<div class="pane-inner"><p class="block-note">Couldn't load the terms.</p></div>`;
    }
  }

  ["open-terms", "open-terms-2"].forEach((id) => {
    const el = $(id);
    if (el) el.onclick = openTerms;
  });
  $("open-terms-inline").onclick = () => {
    $("auth-modal").hidden = true;
    openTerms();
  };
  $("terms-back").onclick = () => window.showView("search-view");
  A.openTerms = openTerms;

  /* ── jargon translation ──────────────────────────── */

  A.translate = async (body, subject) =>
    api("/api/translate", { method: "POST", body: JSON.stringify({ body, subject }) });

  A.openAuth = openAuth;
  A.openAccount = openAccount;
  A.openMessages = openMessages;
  A.refresh = refresh;

  $("nav-account").onclick = () => (A.user ? openAccount() : openAuth("login"));
  $("nav-messages").onclick = openMessages;
  $("account-back").onclick = () => window.showView("search-view");
  $("messages-back").onclick = () => openAccount();

  refresh();
  loadOptions();
})();
