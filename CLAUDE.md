# ResearchBridge — Build Spec

**One-liner:** Princeton has a searchable map of who knows what — it's just scattered across lab pages, papers, and grant records. ResearchBridge turns that into a matching engine that connects student founders to the faculty and researchers who can actually solve their technical problem.

**What it is NOT:** a profile-matching app. Profiles are the weak version of this. The strong version matches on **published work** — which is public, already exists, and doesn't require anyone to sign up.

---

## The insight that makes this non-obvious

Every "dating app for X" dies of the cold start problem: empty on both sides, nobody returns. This one doesn't, because **one side of the marketplace is already populated.**

Princeton faculty and grad student research output is public and indexed — papers, abstracts, lab pages, course listings. We can build the entire supply side from public data before a single user signs up. A founder opens the app on day one and finds 800 researchers, not six.

That is the whole pitch. Lead with it.

---

## The design correction that matters most

**Faculty will not swipe.** They will not install an app, build a profile, or check a match queue. Any design requiring reciprocal faculty engagement fails in the real world, and a judge who has ever emailed a professor will know it.

So the flow is **asymmetric**:

- **Founder side (active):** describes a problem, browses evidence-backed matches, swipes to shortlist
- **Researcher side (passive by default):** discoverable from public work with no signup required; optional lightweight opt-in to receive intros
- **Output:** not a "match" — a **warm intro**. A specific, credible, pre-drafted email citing the researcher's actual publications and explaining the connection

Swiping still exists as the founder-side UI. It just isn't load-bearing.

---

## Match on problems, not tags

Weak: *"I'm a founder in biotech"* → matched to faculty tagged `biotech`.

Strong: *"Our assay degrades above 40°C and we can't stabilize the enzyme"* → semantic search over publication abstracts → *"Prof. Chen's 2024 paper on thermostable enzyme scaffolds addresses this directly."*

**Every match must be explainable with evidence.** Never show a bare "92% match." Show:

> **Prof. Sarah Chen** — Chemical & Biological Engineering
> Matched because: *"Thermostable enzyme design for industrial catalysis"* (Nature Catalysis, 2024) directly addresses your stabilization problem.
> Also: teaches CBE 433, currently advising 3 senior theses in adjacent areas.
> → [Draft intro email]

The explanation is the product. The swipe is the wrapper.

---

## Data sources (all public, no scraping gray areas)

- **OpenAlex API** — free, open, no key required; full publication records for any institution. Primary source. Filter by Princeton institution ID.
- **Semantic Scholar API** — free tier, abstracts + citation graph. Good secondary.
- Princeton department faculty listings for names, titles, contact routing
- Course catalog — for the "you're already in their class" signal, which is a genuinely strong warm-intro hook

Respect `robots.txt` and rate limits. OpenAlex covers most of what's needed without scraping anything.

---

## Architecture

```
[ OpenAlex ingest ] → embeddings → [ vector index ] → [ matching API ] → [ swipe UI ]
     one-time              cheap        flat file          FastAPI          Next/Gradio
```

No GPU. No training. Embeddings via `text-embedding-3-small` (cents for thousands of abstracts). Vector search over a few thousand researchers doesn't need a vector DB — numpy cosine similarity is fine and has zero setup cost.

---

## Repo structure

```
researchbridge/
├── CLAUDE.md
├── ingest/
│   ├── openalex.py      # pull Princeton researchers + abstracts
│   ├── embed.py         # abstracts → vectors
│   └── build_index.py   # → data/index.npz + data/researchers.json
├── api/
│   ├── match.py         # problem text → ranked researchers + evidence
│   └── intro.py         # LLM-drafted outreach email
├── app/
│   └── app.py           # swipe UI
└── data/
```

---

## PHASE 1 — Build the supply side

**Goal:** a searchable index of Princeton researchers, built entirely from public data.

- Pull Princeton-affiliated works from OpenAlex (last ~5 years to keep it current)
- Group by author; keep researchers with ≥3 recent works
- Per researcher: name, dept, titles + abstracts, topic tags, recent-work count
- Embed a concatenation of their recent abstracts → one vector per researcher
- Save to `data/index.npz` + `data/researchers.json`

**Acceptance:** ≥500 Princeton researchers indexed with embeddings. Querying a free-text problem returns sensible names.

**Do this first.** It's the entire differentiator and it de-risks the demo — even if the UI is half-built, a working index demos as a search tool.

---

## PHASE 2 — Matching + explanation

- `match(problem_text, k=20)` → embed query, cosine similarity, return ranked researchers
- **Evidence extraction:** for each match, identify which specific paper drove it (highest-similarity individual abstract, not just the aggregate) — this is what makes explanations concrete
- **LLM explanation:** one sentence connecting their work to the founder's stated problem. Cite the paper by title and year.
- **Boost signals:** same department as founder's major, teaches a course the founder has taken, has advised undergrad theses (signals openness to student contact)

**Acceptance:** given a realistic founder problem, returns 10 matches each with a specific paper cited and a one-line rationale.

---

## PHASE 3 — The swipe UI

Keep it, it's fine, it makes the demo legible. Just don't let it be the substance.

- Card per researcher: name, dept, the matched paper, the one-line rationale, warm-intro signals
- Swipe right → shortlist; left → dismiss (and down-weight that topic cluster for subsequent cards)
- Shortlist view → **"Draft intro"** button per person

**The money feature — the intro email.** LLM-drafted, specific, and credible:

> Subject: Undergrad question re: your work on thermostable enzyme scaffolds
>
> Prof. Chen — I'm a junior in CBE working on [project]. I read your 2024 Nature Catalysis paper on enzyme scaffolds; we're hitting the stabilization problem you describe in section 3. Would you have 15 minutes...

This is the moment judges understand the product. A match is a number; a ready-to-send email that cites a real paper is a tool someone would use today.

---

## PHASE 4 — Demo hardening

- Precompute matches for 3–4 realistic founder scenarios so the demo never depends on a live API call
- Record a screen capture of the working flow
- Verify it runs with wifi off
- Limitations slide: public data only, no faculty verification, matching is a discovery aid not a recommendation

---

## Demo script (3 minutes)

1. "Princeton has 1,200 researchers. A founder needs exactly one of them, and has no way to find them." — show the problem
2. Type a real technical blocker into the box
3. Ten researchers appear, each with a cited paper and a reason
4. Swipe through, shortlist two
5. Click "Draft intro" → a specific, sendable email appears
6. "We built the supply side from public data. There were 800 researchers in here before we had a single user."

Point 6 is the one that separates this from every other matching app they'll see. Say it out loud.

---

## Do NOT

- Do not require faculty signup for the core flow.
- Do not match on self-reported tags or profile fields.
- Do not show match percentages without evidence.
- Do not build auth, accounts, or a database for a 5-day demo.
- Do not scrape anything OpenAlex already provides.
- Do not let the swipe UI consume more than one day.

---

## Honest weaknesses — own them before a judge finds them

- **Retention is structurally bad.** Finding a collaborator is a one-time need. Counter: expand to ongoing research-opportunity discovery, not just founder matching.
- **Thin demand side.** Princeton has maybe 200–400 startup-inclined students. Counter: the tool works for any student seeking a research mentor, which is a far larger population and a natural expansion.
- **Cold outreach still has low response rates.** Counter: the intro quality is the lever, and citing specific recent work measurably outperforms generic cold email.

---

## Suggested first message to Claude Code

> Read CLAUDE.md. Phase 1 only: write `ingest/openalex.py` to pull Princeton-affiliated researchers and their recent abstracts from the OpenAlex API, then `ingest/embed.py` and `ingest/build_index.py` to produce the searchable index. Target 500+ researchers. Don't build the API or UI yet.
