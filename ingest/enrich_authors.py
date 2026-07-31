"""Add author-level signals (h-index, career span) to the researcher records.

OpenAlex has no "is faculty" field, so we derive a seniority heuristic from
public author metadata: a long publication career plus a high h-index reads as
faculty/PI; a short recent burst reads as a grad student or postdoc. This is a
proxy, not ground truth — it is used to rank, never asserted to the user.

Reads/writes data/researchers_raw.json in place (adds an "author_stats" key).

Usage:
    python ingest/enrich_authors.py
"""

import json
import time
from datetime import datetime
from pathlib import Path

import requests
from tqdm import tqdm

API = "https://api.openalex.org/authors"
PRINCETON_ID = "I20089843"
MAILTO = "azeng0601@gmail.com"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
THIS_YEAR = datetime.now().year


def fetch_authors():
    params = {
        "filter": f"last_known_institutions.id:{PRINCETON_ID}",
        "per-page": 200,
        "cursor": "*",
        "mailto": MAILTO,
        "select": "id,display_name,works_count,cited_by_count,summary_stats,affiliations",
    }
    session = requests.Session()
    stats = {}
    with tqdm(desc="author pages", unit="page") as bar:
        while True:
            for attempt in range(5):
                resp = session.get(API, params=params, timeout=60)
                if resp.status_code == 200:
                    break
                time.sleep(2**attempt)
            resp.raise_for_status()
            page = resp.json()
            for a in page["results"]:
                years = [
                    y
                    for affil in a.get("affiliations") or []
                    for y in affil.get("years") or []
                ]
                stats[a["id"]] = {
                    "h_index": (a.get("summary_stats") or {}).get("h_index", 0),
                    "works_count": a.get("works_count", 0),
                    "cited_by_count": a.get("cited_by_count", 0),
                    "career_start": min(years) if years else None,
                }
            bar.update(1)
            cursor = page["meta"].get("next_cursor")
            if not cursor:
                return stats
            params["cursor"] = cursor
            time.sleep(0.1)


def seniority(stat):
    """0-1 heuristic for 'is an established PI rather than a trainee'.

    Deliberately smooth: a wrong hard classification on a demo stage is worse
    than a soft ranking signal.
    """
    if not stat:
        return 0.0
    h = stat.get("h_index") or 0
    start = stat.get("career_start")
    span = (THIS_YEAR - start) if start else 0
    h_score = min(h / 30.0, 1.0)          # h=30+ is firmly PI territory
    span_score = min(span / 15.0, 1.0)    # 15+ years at the institution
    return round(0.6 * h_score + 0.4 * span_score, 3)


def main():
    path = DATA_DIR / "researchers_raw.json"
    with open(path) as f:
        payload = json.load(f)

    stats = fetch_authors()
    hit = 0
    for r in payload["researchers"]:
        stat = stats.get(r["id"])
        if stat:
            hit += 1
        r["author_stats"] = stat or {}
        r["seniority"] = seniority(stat)

    with open(path, "w") as f:
        json.dump(payload, f)

    senior = sum(1 for r in payload["researchers"] if r["seniority"] >= 0.5)
    print(
        f"enriched {hit}/{len(payload['researchers'])} researchers "
        f"({senior} scored >=0.5 seniority)"
    )


if __name__ == "__main__":
    main()
