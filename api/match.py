"""Problem text -> ranked Princeton researchers, each with cited evidence.

Scoring is a blend of two similarities:
  best-work  — the single most relevant paper this person has written
  aggregate  — the mean of their recent work, i.e. how central this is to them

Best-work dominates on purpose. A researcher with one paper squarely on the
founder's problem is a better intro than one whose whole portfolio is vaguely
adjacent, and the mean alone buries the former.

Usage:
    python api/match.py "our enzyme assay degrades above 40C" -k 10
    python api/match.py "..." --major "Chemical and Biological Engineering"
    python api/match.py "..." --no-llm      # skip rationale generation
"""

import argparse
import heapq
import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
EMBED_MODEL = "text-embedding-3-small"
CHAT_MODEL = os.environ.get("RB_CHAT_MODEL", "gpt-4.1-mini")

W_BEST = 0.65        # weight on best single paper
W_MEAN = 0.35        # weight on portfolio centrality
POOL = 300           # candidates rescored before boosts are applied


@lru_cache(maxsize=1)
def load_index():
    index = np.load(DATA_DIR / "index.npz")
    with open(DATA_DIR / "researchers.json") as f:
        researchers = json.load(f)
    # rows of work_vecs belonging to each researcher, in researchers[i]["works"] order
    work_rows = [[] for _ in researchers]
    for row, ridx in enumerate(index["work_researcher_idx"]):
        work_rows[int(ridx)].append(row)
    return {
        "researcher_vecs": index["researcher_vecs"],
        "work_vecs": index["work_vecs"],
        "work_rows": work_rows,
        "researchers": researchers,
    }


@lru_cache(maxsize=1)
def _by_id():
    return {r["id"]: r for r in load_index()["researchers"]}


def researcher_by_id(researcher_id):
    return _by_id().get(researcher_id)


def embed_query(text):
    from openai import OpenAI

    load_dotenv(ROOT / ".env")
    resp = OpenAI().embeddings.create(model=EMBED_MODEL, input=[text])
    vec = np.asarray(resp.data[0].embedding, dtype=np.float32)
    return vec / np.linalg.norm(vec)


def warm_signals(researcher, major):
    """Human-readable reasons this person is a plausible, reachable contact."""
    signals = []
    sen = researcher.get("seniority", 0.0)
    stats = researcher.get("author_stats") or {}
    if sen >= 0.5:
        signals.append("Established PI — long publication record at Princeton")
    elif sen < 0.25 and stats.get("works_count", 0) > 0:
        signals.append("Early-career (likely grad student or postdoc) — often more responsive")
    if major and researcher.get("dept") and major.lower() in researcher["dept"].lower():
        signals.append(f"Same field as your major ({researcher['dept']})")
    if researcher.get("works_count_recent", 0) >= 8:
        signals.append(f"Highly active — {researcher['works_count_recent']} papers since 2021")
    if stats.get("h_index"):
        signals.append(f"h-index {stats['h_index']}")
    return signals


def _work_key(work):
    """Identity for dedup. Preprint and published version share a title but not
    an OpenAlex id, so normalized title is the stronger key."""
    title = (work.get("title") or "").lower()
    return "".join(ch for ch in title if ch.isalnum())[:80] or work["id"]


def _score(work_sim, mean_sim, researcher, prefer_faculty):
    score = W_BEST * work_sim + W_MEAN * mean_sim
    if prefer_faculty:
        # modest nudge; never enough to outrank clearly better-matched work.
        # ~a third of authors have no OpenAlex author record (last-known
        # institution elsewhere); they score neutral, not bottom.
        sen = researcher.get("seniority") if (researcher.get("author_stats") or {}) else None
        score += 0.03 * (0.5 if sen is None else sen)
    return score


def match(problem_text, k=10, major=None, prefer_faculty=True):
    idx = load_index()
    qvec = embed_query(problem_text)

    mean_sims = idx["researcher_vecs"] @ qvec
    work_sims = idx["work_vecs"] @ qvec

    # Candidates hold their works ranked by relevance. Papers get claimed by one
    # researcher during selection: co-authors of a hot paper would otherwise
    # occupy half the result list with identical evidence.
    heap = []
    for i in np.argsort(mean_sims)[::-1][:POOL]:
        i = int(i)
        rows = idx["work_rows"][i]
        if not rows:
            continue
        order = np.argsort(work_sims[rows])[::-1]
        r = idx["researchers"][i]
        top = int(order[0])
        heapq.heappush(
            heap,
            (-_score(float(work_sims[rows[top]]), float(mean_sims[i]), r, prefer_faculty),
             i, 0, [int(o) for o in order]),
        )

    results, claimed = [], set()
    while heap and len(results) < k:
        neg_score, i, choice, order = heapq.heappop(heap)
        rows = idx["work_rows"][i]
        r = idx["researchers"][i]
        local = order[choice]
        work = r["works"][local]
        if _work_key(work) in claimed:
            # fall back to this researcher's next-best distinct paper and requeue
            if choice + 1 >= len(order):
                continue
            nxt = order[choice + 1]
            heapq.heappush(
                heap,
                (-_score(float(work_sims[rows[nxt]]), float(mean_sims[i]), r, prefer_faculty),
                 i, choice + 1, order),
            )
            continue
        claimed.add(_work_key(work))
        results.append(
            {
                "researcher_id": r["id"],
                "name": r["name"],
                "dept": r["dept"],
                "tags": r["tags"],
                "score": round(-neg_score, 4),
                "best_work_sim": round(float(work_sims[rows[local]]), 4),
                "portfolio_sim": round(float(mean_sims[i]), 4),
                "matched_work": work,
                "signals": warm_signals(r, major),
            }
        )
    return results


RATIONALE_PROMPT = """You explain why a Princeton researcher's published work is relevant to a student founder's technical problem.

For each researcher, write ONE sentence (max 30 words) connecting their specific paper to the problem. Reference what the paper actually does. Be concrete and factual — no hype, no "perfect match", no invented claims about the researcher.

If a paper is only loosely related, say so plainly (e.g. "adjacent: works on X, not Y directly"). An honest weak match is more useful than an overstated one.

Each sentence is shown on its own card, so it must stand alone. Never refer to other entries, indices, or the list ("duplicate of paper 0", "same as above", "unlike #2"). The reader sees only your one sentence.

Return JSON: {"rationales": [{"i": <index>, "text": "<sentence>"}]}"""


def add_rationales(problem_text, matches):
    """One batched LLM call for all matches — cheaper and faster than k calls."""
    from openai import OpenAI

    load_dotenv(ROOT / ".env")
    payload = {
        "problem": problem_text,
        "researchers": [
            {
                "i": n,
                "name": m["name"],
                "field": m["dept"],
                "paper_title": m["matched_work"]["title"],
                "paper_year": m["matched_work"]["year"],
                "paper_abstract": (m["matched_work"]["abstract"] or "")[:900],
            }
            for n, m in enumerate(matches)
        ],
    }
    resp = OpenAI().chat.completions.create(
        model=CHAT_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": RATIONALE_PROMPT},
            {"role": "user", "content": json.dumps(payload)},
        ],
    )
    parsed = json.loads(resp.choices[0].message.content)
    by_i = {r["i"]: r["text"] for r in parsed.get("rationales", [])}
    for n, m in enumerate(matches):
        m["rationale"] = by_i.get(n)
    return matches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("problem", help="the founder's technical problem, in plain language")
    parser.add_argument("-k", type=int, default=10)
    parser.add_argument("--major", default=None, help="founder's department, for a same-field signal")
    parser.add_argument("--no-llm", action="store_true", help="skip rationale generation")
    parser.add_argument("--json", action="store_true", help="dump raw JSON")
    args = parser.parse_args()

    matches = match(args.problem, k=args.k, major=args.major)
    if not args.no_llm:
        matches = add_rationales(args.problem, matches)

    if args.json:
        print(json.dumps(matches, indent=2))
        return

    print(f'\nProblem: "{args.problem}"\n')
    for rank, m in enumerate(matches, 1):
        print(f"{rank:2d}. {m['name']}  —  {m['dept']}   (score {m['score']:.3f})")
        w = m["matched_work"]
        print(f'    Matched on: "{w["title"]}" ({w["year"]})')
        if m.get("rationale"):
            print(f"    Why: {m['rationale']}")
        if m["signals"]:
            print(f"    Signals: {' · '.join(m['signals'])}")
        print()


if __name__ == "__main__":
    main()
