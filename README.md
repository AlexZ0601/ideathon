# ResearchBridge

Connects student founders to the Princeton faculty and researchers who can actually solve their technical problem — by matching on **published work**, not profiles.

Princeton's research output is public and indexed (papers, abstracts, lab pages, courses). ResearchBridge builds the entire supply side of the marketplace from that public data, so a founder opens the app on day one and finds hundreds of researchers — no faculty signup required. Describe a technical blocker in plain language, get evidence-backed matches ("Prof. Chen's 2024 paper on thermostable enzyme scaffolds addresses this directly"), shortlist with a swipe, and generate a specific, credible, ready-to-send intro email that cites their actual work.

Built for the PrincetonBuilds Ideathon.

## How it works

```
[ OpenAlex ingest ] → embeddings → [ vector index ] → [ matching API ] → [ swipe UI ]
```

1. **Ingest** (`ingest/`) — pull Princeton-affiliated researchers and recent abstracts from the OpenAlex API, embed each researcher's work, build a flat-file vector index.
2. **Matching** (`api/`) — embed a founder's problem statement, rank researchers by cosine similarity, and attach evidence: the specific paper that drove the match plus a one-line rationale.
3. **App** (`app/`) — swipe UI for browsing matches, a shortlist, and the "Draft intro" button that produces a sendable outreach email.

## Structure

```
ingest/   OpenAlex pull, embedding, index build
api/      matching + intro-email drafting
app/      FastAPI server, swipe UI, demo cache warmer
data/     generated index + researcher records (gitignored)
```


## Building the index

Put `OPENAI_API_KEY=...` in a `.env` file at the repo root, then:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python ingest/openalex.py        # ~4 min, no API key needed
.venv/bin/python ingest/enrich_authors.py  # ~1 min, adds h-index / career span
.venv/bin/python ingest/embed.py           # ~7 min, ~$0.05
.venv/bin/python ingest/build_index.py
```

Current index: 4,159 Princeton researchers with 3+ works since Aug 2021, 23,112 embedded abstracts.

## Matching

```bash
.venv/bin/python api/match.py "our enzyme assay degrades above 40C" -k 10
```

Flags: `--major` for a same-field signal, `--no-llm` to skip rationale generation, `--json` for raw output. Rationales use `gpt-4.1-mini` (override with `RB_CHAT_MODEL`).

Ranking blends the single most relevant paper (65%) with portfolio centrality (35%), so someone with one paper squarely on your problem outranks someone vaguely adjacent across the board. Each paper is claimed by one researcher — co-authors of a hot paper would otherwise fill half the list with identical evidence — and preprint/published pairs are deduped by normalized title.

## Running the app

```bash
.venv/bin/uvicorn app.server:app --port 8000
```

Open **http://127.0.0.1:8000**. Describe a problem (or click a scenario chip), swipe through
matches with the arrow keys or by dragging, then hit **Draft intro** on anyone shortlisted.

Leave that terminal running for as long as you're demoing. If it stops, the page still loads
from browser cache but every action fails — the app now says so explicitly instead of blaming
your API key.

Fill in **Your details** on the landing page so drafted emails are signed by you. It's stored
in `localStorage`, never sent anywhere except to draft the email.

Intro emails use `gpt-4.1` (override with `RB_INTRO_MODEL`).

## Demo hardening

Warm the cache before presenting, so no step on stage waits on the network:

```bash
.venv/bin/python -m app.precompute --name "Alex Zeng" --major "Computer Science"
```

This runs all four scenarios plus intro emails for each one's top three matches into
`data/cache/`. Pass the same details you typed into **Your details** — the founder profile is
part of the intro cache key, so a mismatch silently falls back to a live API call.

Verified: with `.env` removed entirely, all four scenarios still return 12 matches and a
drafted intro from cache, in ~10ms. The frontend ships no CDN assets — system fonts, local
CSS and JS only — so the whole demo path runs with wifi off.

Still on you before Sunday: **record a screen capture of the working demo.** If something
breaks live, you play the tape.

## Limitations

- Built on public data only; researchers are not verified or opted in by default.
- Matching is a discovery aid, not a recommendation.
- OpenAlex has no department field; `dept` is the researcher's dominant topic subfield, so `--major` only matches against subfield names.
- Seniority ("Established PI" vs "Early-career") is a heuristic from h-index and career span, not ground truth. About a third of authors have no OpenAlex author record and are scored neutrally.
- No course-catalog data yet, so the "you're already in their class" warm-intro signal is not implemented.
- We never guess contact addresses. OpenAlex has no email data, so the app tells you to look the recipient up on their department page rather than inventing a netid.
