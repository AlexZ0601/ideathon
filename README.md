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

## Limitations

- Built on public data only; researchers are not verified or opted in by default.
- Matching is a discovery aid, not a recommendation.
