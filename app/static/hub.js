/* Cofounder Hub — find people at your school who are also building something.

   This is the one surface in cofoundr with a real cold-start problem, and it
   is treated honestly rather than padded. The researcher index has 4,159
   people in it from public data; they are not in here, because being publicly
   published is not consent to be pitched as a cofounder. The hub only shows
   accounts that signed up and left themselves visible. When it is empty it
   says so. */

(() => {
  const $ = (id) => document.getElementById(id);

  const esc = (s) => {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
  };

  const state = { q: "", school: null, org: null, facets: { schools: [], orgs: [] } };

  async function api(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error((await res.json()).detail || res.status);
    return res.json();
  }

  function url() {
    const p = new URLSearchParams();
    if (state.q.trim()) p.set("q", state.q.trim());
    if (state.school) p.set("school", state.school);
    if (state.org) p.set("org", state.org);
    const s = p.toString();
    return "/api/hub" + (s ? `?${s}` : "");
  }

  async function load() {
    let data;
    try {
      data = await api(url());
    } catch (e) {
      $("hub-list").innerHTML = `<p class="hub-empty">Couldn't load the hub. ${esc(e.message)}</p>`;
      return;
    }
    state.facets = data.facets;
    paintFacets();
    paintList(data);
  }

  function paintFacets() {
    const box = $("hub-facets");
    const chip = (label, count, active, onClick) => {
      const b = document.createElement("button");
      b.className = "pill" + (active ? " is-on" : "");
      b.innerHTML = `${esc(label)} <span class="pill-n">${count}</span>`;
      b.onclick = onClick;
      return b;
    };

    box.innerHTML = "";
    const { schools, orgs } = state.facets;
    if (!schools.length && !orgs.length) return;

    if (schools.length) {
      const row = document.createElement("div");
      row.className = "facet-row";
      row.innerHTML = `<span class="facet-label">School</span>`;
      schools.forEach((s) =>
        row.append(
          chip(s.name, s.count, state.school === s.name, () => {
            state.school = state.school === s.name ? null : s.name;
            load();
          })
        )
      );
      box.append(row);
    }

    if (orgs.length) {
      const row = document.createElement("div");
      row.className = "facet-row";
      row.innerHTML = `<span class="facet-label">Organization</span>`;
      orgs.forEach((o) =>
        row.append(
          chip(o.name, o.count, state.org === o.name, () => {
            state.org = state.org === o.name ? null : o.name;
            load();
          })
        )
      );
      box.append(row);
    }
  }

  function paintList(data) {
    const list = $("hub-list");
    $("hub-count").textContent = data.total
      ? `${data.total} ${data.total === 1 ? "person" : "people"} listed`
      : "nobody listed yet";

    if (!data.people.length) {
      const filtered = state.q || state.school || state.org;
      list.innerHTML = filtered
        ? `<p class="hub-empty">Nobody matches that yet. <button class="link-btn" id="hub-clear">Clear filters</button></p>`
        : `<div class="hub-empty hub-cold">
             <h3>Nobody has listed themselves yet.</h3>
             <p>
               This is the one part of cofoundr that can't be built from public data.
               The 4,159 researchers in the index never signed up — being published
               isn't consent to be pitched as a cofounder. So the hub starts empty
               and fills as people opt in.
             </p>
             <button class="btn-primary" id="hub-join"><span>Add yourself</span></button>
           </div>`;
      $("hub-clear") &&
        ($("hub-clear").onclick = () => {
          state.q = "";
          state.school = null;
          state.org = null;
          $("hub-q").value = "";
          load();
        });
      $("hub-join") && ($("hub-join").onclick = openListing);
      return;
    }

    list.innerHTML = data.people
      .map(
        (p) => `
        <article class="hub-card">
          <div class="hub-card-main">
            <h3>${esc(p.name)}</h3>
            <p class="hub-meta">
              ${p.school ? `<span class="hub-tag school">${esc(p.school)}</span>` : ""}
              ${p.org ? `<span class="hub-tag org">${esc(p.org)}</span>` : ""}
              ${p.major ? `<span class="hub-tag">${esc(p.major)}</span>` : ""}
              ${p.year ? `<span class="hub-tag">${esc(p.year)}</span>` : ""}
            </p>
            ${p.blurb ? `<p class="hub-blurb">${esc(p.blurb)}</p>` : ""}
          </div>
          <button class="btn-primary" data-msg="${p.id}" data-name="${esc(p.name)}">
            <span>Message</span>
          </button>
        </article>`
      )
      .join("");

    list.querySelectorAll("[data-msg]").forEach((b) => {
      b.onclick = () => openCompose(+b.dataset.msg, b.dataset.name);
    });
  }

  /* ── compose ─────────────────────────────────────── */

  function openCompose(userId, name) {
    if (!window.Accounts.user) {
      window.Accounts.openAuth("signup", () => openCompose(userId, name));
      return;
    }
    const modal = $("intro-modal");
    modal.hidden = false;
    $("intro-body").innerHTML = `
      <div class="email-field"><b>To</b><span>${esc(name)}</span></div>
      <label class="field" style="margin-top:14px">Subject
        <input type="text" id="hub-subject" value="Building something at your school">
      </label>
      <label class="field" style="margin-top:12px">Message
        <textarea id="hub-body" rows="7" placeholder="What you're building, and what you're looking for."></textarea>
      </label>`;
    $("intro-hint").textContent = "Goes straight to their cofoundr inbox.";
    $("copy-btn").hidden = true;

    const send = $("send-btn");
    send.querySelector("span").textContent = "Send message";
    send.onclick = async () => {
      const body = $("hub-body").value.trim();
      if (!body) return;
      send.disabled = true;
      try {
        const res = await fetch("/api/messages", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            to_user_id: userId,
            subject: $("hub-subject").value.trim() || "Intro",
            body,
          }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail);
        modal.hidden = true;
        window.toastMsg?.(data.notice, 5000);
        await window.Accounts.refresh();
      } catch (e) {
        window.toastMsg?.(e.message);
      } finally {
        send.disabled = false;
        // hand the buttons back to the researcher-intro flow
        send.onclick = null;
        $("copy-btn").hidden = false;
        send.querySelector("span").textContent = "Send via cofoundr";
      }
    };
  }

  function openListing() {
    $("intro-modal").hidden = true;
    window.Accounts.openAccount();
  }

  /* ── wiring ──────────────────────────────────────── */

  let timer;
  $("hub-q").oninput = (e) => {
    state.q = e.target.value;
    clearTimeout(timer);
    timer = setTimeout(load, 220);
  };

  $("hub-back").onclick = () => window.showView("search-view");
  $("hub-edit").onclick = openListing;

  window.Hub = {
    open() {
      window.showView("hub-view");
      load();
    },
  };
})();
