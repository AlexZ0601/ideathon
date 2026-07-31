"""Fetch the two sides of the White Space Map and embed them.

Supply — what already exists: YC companies (public dataset, ~6k with one-liners
and long descriptions).

Demand — what people are asking for: Hacker News. Reddit was the obvious source
but its public JSON endpoints now return a block page to unauthenticated
clients, and the official API needs OAuth credentials per user. HN's Algolia
index is open, keyless, and startup-adjacent, which actually pairs better with
YC supply than a general subreddit would.

Writes:
    data/ws_supply.json   [{id, name, text, batch, industry}]
    data/ws_demand.json   [{id, title, text, url, points, author, created}]
    data/ws_vecs.npz      supply_vecs, demand_vecs (L2-normalized float32)

Usage:
    python ingest/whitespace.py [--demand-pages 40] [--skip-embed]
"""

import argparse
import json
import re
import time
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
YC_URL = "https://yc-oss.github.io/api/companies/all.json"
HN_API = "https://hn.algolia.com/api/v1/search_by_date"
EMBED_MODEL = "text-embedding-3-small"

# Phrases people use when describing an unmet need. Searching these beats
# pulling a feed wholesale: it filters for demand-shaped language up front.
# The first pass pulled bulk Ask HN too, which turned out to be mostly career
# and life questions -- it produced one 445-post blob about being a lonely
# developer and buried the actual product gaps. Targeted queries only.
DEMAND_QUERIES = [
    "I wish there was a tool",
    "why is there no good",
    "is there a better way to",
    "frustrated with existing tools",
    "anyone know a tool for",
    "we ended up building our own",
    "still doing this manually",
    "spreadsheet hell",
    "no good solution exists",
    "biggest pain point",
    "wastes hours every week",
    "hate how hard it is to",
    "why does no software do",
    "every tool I tried",
    "had to write a script to",
    "there has to be a better way",
    "duct tape and scripts",
    "manual process every month",
    "we track this in a spreadsheet",
    "existing tools are too expensive",
    "enterprise software is terrible",
    "why is this still so hard",
    "wish someone would build",
    "gave up and did it by hand",
    "the tooling for this is bad",
    "no API for this",
    "workflow is a nightmare",
    "takes me all day to",
    "spent a week automating",
    "onboarding is painful",
    "compliance paperwork",
    "reconciling data between systems",
]

# Demand-shaped language, used to filter noise out of keyword hits.
COMPLAINT_RE = re.compile(
    r"\b(wish|frustrat|painful|pain point|manual|tedious|no (good )?(tool|option|solution)|"
    r"nightmare|clunky|terrible|awful|hate|struggl|workaround|hack together|by hand|"
    r"too expensive|why is there no|better way|annoying|broken|lacking|missing)\b",
    re.I,
)

TAG_RE = re.compile(r"<[^>]+>")


def clean(text):
    return TAG_RE.sub(" ", text or "").replace("&#x27;", "'").replace("&quot;", '"').strip()


def fetch_supply():
    print("fetching YC companies…")
    companies = requests.get(YC_URL, timeout=120).json()
    out = []
    for c in companies:
        one = (c.get("one_liner") or "").strip()
        long_desc = (c.get("long_description") or "").strip()
        if not one and not long_desc:
            continue
        out.append(
            {
                "id": f"yc:{c.get('id')}",
                "name": c.get("name"),
                "text": f"{c.get('name')}. {one}. {long_desc}"[:1200],
                "one_liner": one[:300],
                "batch": c.get("batch"),
                "industry": c.get("industry"),
                "url": c.get("url") or c.get("website"),
            }
        )
    print(f"  {len(out)} companies with descriptions")
    return out


def fetch_demand(pages_per_query):
    """Ask HN posts plus keyword searches for demand-shaped language."""
    session = requests.Session()
    seen, out = set(), []

    def collect(params, label):
        for page in range(pages_per_query):
            params = {**params, "page": page, "hitsPerPage": 100}
            for attempt in range(4):
                r = session.get(HN_API, params=params, timeout=45)
                if r.status_code == 200:
                    break
                time.sleep(2**attempt)
            else:
                return
            hits = r.json().get("hits", [])
            if not hits:
                return
            for h in hits:
                oid = h.get("objectID")
                title = clean(h.get("title") or h.get("story_title"))
                body = clean(h.get("story_text") or h.get("comment_text"))
                text = f"{title}. {body}".strip(". ")
                # short posts carry no semantic signal worth embedding, and
                # keyword hits still need to actually read like a complaint
                if oid in seen or len(text) < 120 or not COMPLAINT_RE.search(text):
                    continue
                seen.add(oid)
                out.append(
                    {
                        "id": f"hn:{oid}",
                        "title": title[:300] or "(comment)",
                        "text": text[:1500],
                        "url": f"https://news.ycombinator.com/item?id={oid}",
                        "points": h.get("points") or 0,
                        "author": h.get("author"),
                        "created": (h.get("created_at") or "")[:10],
                        "source": label,
                    }
                )
            time.sleep(0.15)

    for q in tqdm(DEMAND_QUERIES, desc="demand queries"):
        collect({"query": q, "tags": "(story,comment)"}, q)

    print(f"  {len(out)} demand posts")
    return out


def embed_all(texts, batch=96):
    from openai import OpenAI

    load_dotenv(ROOT / ".env")
    client = OpenAI()
    vecs = []
    for i in tqdm(range(0, len(texts), batch), desc="embedding"):
        chunk = texts[i : i + batch]
        for attempt in range(5):
            try:
                resp = client.embeddings.create(model=EMBED_MODEL, input=chunk)
                break
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(2**attempt)
        vecs.extend(d.embedding for d in resp.data)
    m = np.asarray(vecs, dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    return m


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--demand-pages", type=int, default=4, help="pages per demand query")
    p.add_argument("--skip-embed", action="store_true")
    args = p.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    supply = fetch_supply()
    demand = fetch_demand(args.demand_pages)

    with open(DATA_DIR / "ws_supply.json", "w") as f:
        json.dump(supply, f)
    with open(DATA_DIR / "ws_demand.json", "w") as f:
        json.dump(demand, f)

    if args.skip_embed:
        print("skipping embeddings")
        return

    supply_vecs = embed_all([s["text"] for s in supply])
    demand_vecs = embed_all([d["text"] for d in demand])
    np.savez(DATA_DIR / "ws_vecs.npz", supply_vecs=supply_vecs, demand_vecs=demand_vecs)
    print(f"\nsupply {supply_vecs.shape}  demand {demand_vecs.shape}")


if __name__ == "__main__":
    main()
