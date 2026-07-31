"""Warm the cache for every demo scenario so the presentation needs no network.

Runs each scenario through match + rationales, then drafts an intro email for
the top N researchers of each. Everything lands in data/cache/ under the same
keys the server reads, so the live app hits disk instead of the API.

Usage:
    .venv/bin/python -m app.precompute            # top 3 intros per scenario
    .venv/bin/python -m app.precompute --intros 5
    .venv/bin/python -m app.precompute --refresh  # rebuild even if cached
"""

import argparse

from app.server import (
    CACHE_DIR,
    SCENARIOS,
    Founder,
    IntroRequest,
    MatchRequest,
    api_intro,
    api_match,
)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--intros", type=int, default=3, help="intros to pre-draft per scenario")
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--k", type=int, default=12)
    # The founder profile is part of the intro cache key, so warming the cache
    # with the wrong one means the demo still calls the API live.
    p.add_argument("--name", help="your name, as the app's profile panel has it")
    p.add_argument("--year", default="junior")
    p.add_argument("--major")
    p.add_argument("--project")
    args = p.parse_args()

    founder_kwargs = {
        k: v
        for k, v in {
            "name": args.name,
            "year": args.year,
            "major": args.major,
            "project": args.project,
        }.items()
        if v is not None
    }
    founder = Founder(**founder_kwargs) if args.name else Founder()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    total_intros = 0

    for scenario in SCENARIOS:
        problem = scenario["text"]
        result = api_match(MatchRequest(problem=problem, k=args.k, refresh=args.refresh))
        matches = result["matches"]
        rationales = sum(1 for m in matches if m.get("rationale"))
        print(
            f"\n{scenario['label']}: {len(matches)} matches "
            f"({rationales} with rationales){' [cached]' if result['cached'] else ''}"
        )

        for m in matches[: args.intros]:
            email = api_intro(
                IntroRequest(
                    researcher_id=m["researcher_id"],
                    work_id=m["matched_work"]["id"],
                    problem=problem,
                    founder=founder,
                    refresh=args.refresh,
                )
            )
            total_intros += 1
            tag = "cached" if email["cached"] else "drafted"
            print(f"  - {m['name']}: {email['subject']} [{tag}]")

    files = sorted(CACHE_DIR.glob("*.json"))
    size = sum(f.stat().st_size for f in files) / 1024
    print(
        f"\n{len(SCENARIOS)} scenarios, {total_intros} intro emails cached. "
        f"{len(files)} files, {size:.0f} KB in {CACHE_DIR}"
    )


if __name__ == "__main__":
    main()
