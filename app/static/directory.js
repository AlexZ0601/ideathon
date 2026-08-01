/* Researcher Directory — browse all 4,159, not just search results.

   The professor-side counterpart to the Cofounder Hub, with one important
   difference: this one is not cold-start limited. Everyone is already in it,
   built from public data, before a single person signed up. That contrast is
   the whole product thesis, so the two hubs sit side by side on purpose. */

(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
  };

  const PAGE = 24;
  const state = { q: "", dept: null, sen: "", offset: 0, total: 0, loading: false };

  function url() {
    const p = new URLSearchParams({ offset: state.offset, limit: PAGE });
    if (state.q.trim()) p.set("q", state.q.trim());
    if (state.dept) p.set("dept", state.dept);
    if (state.sen) p.set("seniority", state.sen);
    return `/api/researchers/browse?${p}`;
  }

  async function load(append = false) {
    if (state.loading) return;
    state.loading = true;
    try {
      const res = await fetch(url());
      const d = await res.json();
      state.total = d.total;
      if (!append) paintFacets(d.facets.depts);
      paintGrid(d.researchers, append);
      $("dir-count").textContent = `${d.total.toLocaleString()} researcher${d.total === 1 ? "" : "s"}`;
      $("dir-more").hidden = !d.has_more;
    } finally {
      state.loading = false;
    }
  }

  function paintFacets(depts) {
    const box = $("dir-facets");
    box.innerHTML = "";
    const row = document.createElement("div");
    row.className = "facet-row";
    row.innerHTML = `<span class="facet-label">Field</span>`;
    depts.forEach((d) => {
      const b = document.createElement("button");
      b.className = "pill" + (state.dept === d.name ? " is-on" : "");
      b.innerHTML = `${esc(d.name)} <span class="pill-n">${d.count}</span>`;
      b.onclick = () => {
        state.dept = state.dept === d.name ? null : d.name;
        state.offset = 0;
        load();
      };
      row.append(b);
    });
    box.append(row);
  }

  function paintGrid(rows, append) {
    const grid = $("dir-grid");
    if (!append) grid.innerHTML = "";
    if (!rows.length && !append) {
      grid.innerHTML = `<p class="hub-empty">Nobody matches that filter.</p>`;
      return;
    }
    const html = rows
      .map((r) => {
        const pi = (r.seniority ?? 0) >= 0.5;
        return `
        <article class="dir-card">
          <header>
            <h3>${esc(r.name)}</h3>
            ${r.claimed ? `<span class="dir-claimed">on cofoundr</span>` : ""}
          </header>
          <p class="dir-dept">${esc(r.dept || "Princeton University")}</p>
          <p class="dir-recent">${esc(r.recent)}</p>
          <div class="dir-stats">
            <span class="${pi ? "is-pi" : ""}">${pi ? "Established PI" : "Early-career"}</span>
            <span>${r.works} papers</span>
            ${r.h_index ? `<span>h-index ${r.h_index}</span>` : ""}
          </div>
          <button class="ghost-btn dir-find" data-name="${esc(r.name)}" data-topic="${esc(r.tags?.[0] || r.dept || "")}">
            See their work
          </button>
        </article>`;
      })
      .join("");
    grid.insertAdjacentHTML("beforeend", html);

    grid.querySelectorAll(".dir-find").forEach((b) => {
      if (b.dataset.wired) return;
      b.dataset.wired = "1";
      // hand off to the matcher so the directory isn't a dead end
      b.onclick = () => {
        const topic = b.dataset.topic || b.dataset.name;
        window.showView("search-view");
        const input = $("problem-input");
        input.value = topic;
        input.focus();
        input.scrollIntoView({ block: "center" });
      };
    });
  }

  let timer;
  $("dir-q").oninput = (e) => {
    state.q = e.target.value;
    state.offset = 0;
    clearTimeout(timer);
    timer = setTimeout(() => load(), 220);
  };

  document.querySelectorAll("#dir-sen .seg-btn").forEach((b) => {
    b.onclick = () => {
      state.sen = b.dataset.sen;
      state.offset = 0;
      document.querySelectorAll("#dir-sen .seg-btn").forEach((x) =>
        x.classList.toggle("is-on", x === b)
      );
      load();
    };
  });

  $("dir-more").onclick = () => {
    state.offset += PAGE;
    load(true);
  };
  $("dir-back").onclick = () => window.showView("search-view");

  window.Directory = {
    open() {
      window.showView("dir-view");
      if (!state.total) load();
    },
  };
})();
