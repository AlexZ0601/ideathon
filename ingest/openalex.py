"""Pull Princeton-affiliated researchers and their recent abstracts from OpenAlex.

Output: data/researchers_raw.json — one record per researcher with >= MIN_WORKS
recent works, each carrying title, year, abstract, and topic info.

Usage:
    python ingest/openalex.py [--from-date 2021-08-01] [--max-pages 400]
"""

import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from tqdm import tqdm

API = "https://api.openalex.org/works"
PRINCETON_ID = "I20089843"
MAILTO = "azeng0601@gmail.com"  # OpenAlex polite-pool contact
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

MIN_WORKS = 3        # keep researchers with at least this many recent works
MAX_AUTHORS = 50     # skip mega-collaboration papers; they carry no matching signal
MAX_STORED = 8       # abstracts kept per researcher (most recent first)
ABSTRACT_CHARS = 3000


def reconstruct_abstract(inverted_index):
    """OpenAlex ships abstracts as {word: [positions]}; rebuild the text."""
    if not inverted_index:
        return None
    positions = [(p, word) for word, plist in inverted_index.items() for p in plist]
    positions.sort()
    return " ".join(word for _, word in positions)


def fetch_pages(from_date, max_pages):
    params = {
        "filter": f"institutions.id:{PRINCETON_ID},from_publication_date:{from_date},has_abstract:true",
        "per-page": 200,
        "cursor": "*",
        "mailto": MAILTO,
        "select": "id,title,publication_year,authorships,abstract_inverted_index,primary_topic",
    }
    session = requests.Session()
    with tqdm(desc="pages", unit="page") as bar:
        for _ in range(max_pages):
            for attempt in range(5):
                resp = session.get(API, params=params, timeout=60)
                if resp.status_code == 200:
                    break
                time.sleep(2**attempt)
            resp.raise_for_status()
            page = resp.json()
            yield page["results"]
            bar.update(1)
            cursor = page["meta"].get("next_cursor")
            if not cursor:
                return
            params["cursor"] = cursor
            time.sleep(0.1)


def build_researchers(pages):
    researchers = {}
    for works in pages:
        for work in works:
            authorships = work.get("authorships") or []
            if not authorships or len(authorships) > MAX_AUTHORS:
                continue
            abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
            if not abstract:
                continue
            topic = work.get("primary_topic") or {}
            record = {
                "id": work["id"],
                "title": work.get("title") or "",
                "year": work.get("publication_year"),
                "abstract": abstract[:ABSTRACT_CHARS],
                "topic": topic.get("display_name"),
                "subfield": (topic.get("subfield") or {}).get("display_name"),
            }
            for authorship in authorships:
                if not any(
                    inst.get("id", "").endswith(PRINCETON_ID)
                    for inst in authorship.get("institutions") or []
                ):
                    continue
                author = authorship.get("author") or {}
                author_id = author.get("id")
                if not author_id:
                    continue
                entry = researchers.setdefault(
                    author_id, {"id": author_id, "name": author.get("display_name"), "works": []}
                )
                entry["works"].append(record)
    return researchers


def finalize(researchers):
    """Filter to active researchers and derive dept/tag approximations."""
    out = []
    for entry in researchers.values():
        works = sorted(entry["works"], key=lambda w: w["year"] or 0, reverse=True)
        if len(works) < MIN_WORKS:
            continue
        subfields = Counter(w["subfield"] for w in works if w["subfield"])
        topics = Counter(w["topic"] for w in works if w["topic"])
        out.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                # OpenAlex has no department field; the dominant topic subfield
                # is the closest public proxy
                "dept": subfields.most_common(1)[0][0] if subfields else None,
                "tags": [t for t, _ in topics.most_common(3)],
                "works_count_recent": len(works),
                "works": works[:MAX_STORED],
            }
        )
    out.sort(key=lambda r: r["works_count_recent"], reverse=True)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-date", default="2021-08-01")
    parser.add_argument("--max-pages", type=int, default=400)
    args = parser.parse_args()

    researchers = finalize(build_researchers(fetch_pages(args.from_date, args.max_pages)))

    DATA_DIR.mkdir(exist_ok=True)
    out_path = DATA_DIR / "researchers_raw.json"
    with open(out_path, "w") as f:
        json.dump(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "from_date": args.from_date,
                "count": len(researchers),
                "researchers": researchers,
            },
            f,
        )
    print(f"{len(researchers)} researchers with >={MIN_WORKS} recent works -> {out_path}")


if __name__ == "__main__":
    main()
