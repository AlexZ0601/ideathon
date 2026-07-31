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
app/      swipe UI
data/     generated index + researcher records (gitignored)
```

## Building the index

Put `OPENAI_API_KEY=...` in a `.env` file at the repo root, then:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python ingest/openalex.py     # ~4 min, no API key needed
.venv/bin/python ingest/embed.py        # ~7 min, ~$0.05
.venv/bin/python ingest/build_index.py
```

Sanity-check a query:

```bash
.venv/bin/python ingest/build_index.py --query "our enzyme assay degrades above 40C" -k 10
```

Current index: 4,159 Princeton researchers with 3+ works since Aug 2021, 23,112 embedded abstracts.

## Limitations

- Built on public data only; researchers are not verified or opted in by default.
- Matching is a discovery aid, not a recommendation.
- OpenAlex has no department field; `dept` is the researcher's dominant topic subfield, which is an approximation.
- Authors include grad students and postdocs, not just faculty. Seniority is not yet distinguished.
