"""Find white space: demand clusters that sit far from everything already built.

Two scores per demand point, both computed in the original 1536-d embedding
space rather than the UMAP projection. UMAP is for looking at; it distorts
distances badly enough that measuring on it would be measuring the artifact.

    supply_gap      1 - mean cosine similarity to the k nearest YC companies.
                    High = nobody is building near this.
    demand_density  how many other demand posts sit within a similarity
                    threshold. High = this isn't one person having a bad day.

White space is the product of both. A lone weird post scores low on density;
a loud, crowded problem that YC already serves scores low on gap.

Writes data/whitespace.json — 3-D positions for every point plus labeled gap
clusters with their real source posts.

Usage:
    python ingest/whitespace_map.py [--top-frac 0.18] [--no-llm]
"""

import argparse
import json
import os
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LABEL_MODEL = os.environ.get("RB_LABEL_MODEL", "gpt-4.1")

K_SUPPLY = 8           # nearest companies used for the gap score
DENSITY_SIM = 0.72     # cosine similarity that counts as "the same problem"
MIN_CLUSTER = 5        # fewer posts than this isn't a market, it's noise
# Cosine distance in the style-decorrelated space, where points sit further
# apart than in raw embedding space. Swept: 0.45 is too tight to find much,
# 0.60 chains into a 153-post blob, 0.55 holds 17 clusters with sane sizes.
DBSCAN_EPS = 0.55
MAX_CLUSTER_FRAC = 0.25  # a cluster that swallows the corpus is a topic, not a gap


def load():
    with open(DATA_DIR / "ws_supply.json") as f:
        supply = json.load(f)
    with open(DATA_DIR / "ws_demand.json") as f:
        demand = json.load(f)
    z = np.load(DATA_DIR / "ws_vecs.npz")
    return supply, demand, z["supply_vecs"], z["demand_vecs"]


def decorrelate_style(supply_vecs, demand_vecs):
    """Remove each corpus's mean direction before comparing the two.

    Company one-liners are polished marketing copy; HN posts are people
    complaining. Raw embeddings encode that register difference strongly enough
    that the two corpora separate wholesale — every demand point looks "far from
    everything built" for reasons of writing style, which would make the entire
    map an artifact. Subtracting each corpus's own centroid cancels the shared
    style offset and leaves the topical variation, which is what we actually
    want to measure.
    """
    s = supply_vecs - supply_vecs.mean(axis=0, keepdims=True)
    d = demand_vecs - demand_vecs.mean(axis=0, keepdims=True)
    s /= np.linalg.norm(s, axis=1, keepdims=True) + 1e-9
    d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-9
    return s.astype(np.float32), d.astype(np.float32)


def score_demand(demand_vecs, supply_vecs):
    """Returns (supply_gap, demand_density, whitespace) each in [0, 1]."""
    # chunked so the 4k x 6k similarity matrix never lands in memory at once
    gaps = np.empty(len(demand_vecs), dtype=np.float32)
    for i in range(0, len(demand_vecs), 512):
        sims = demand_vecs[i : i + 512] @ supply_vecs.T
        topk = np.partition(sims, -K_SUPPLY, axis=1)[:, -K_SUPPLY:]
        gaps[i : i + 512] = 1.0 - topk.mean(axis=1)

    density = np.empty(len(demand_vecs), dtype=np.float32)
    for i in range(0, len(demand_vecs), 512):
        sims = demand_vecs[i : i + 512] @ demand_vecs.T
        density[i : i + 512] = (sims > DENSITY_SIM).sum(axis=1) - 1  # exclude self

    def norm(a):
        lo, hi = float(a.min()), float(a.max())
        return (a - lo) / (hi - lo) if hi > lo else np.zeros_like(a)

    g, d = norm(gaps), norm(np.log1p(density))
    return g, d, g * d


def cluster_gaps(demand_vecs, whitespace, top_frac):
    from sklearn.cluster import DBSCAN

    n_top = max(MIN_CLUSTER * 3, int(len(whitespace) * top_frac))
    idx = np.argsort(whitespace)[::-1][:n_top]
    labels = DBSCAN(eps=DBSCAN_EPS, min_samples=MIN_CLUSTER, metric="cosine").fit_predict(
        demand_vecs[idx]
    )
    clusters = {}
    for local, lab in enumerate(labels):
        if lab >= 0:
            clusters.setdefault(int(lab), []).append(int(idx[local]))

    cap = max(MIN_CLUSTER * 4, int(n_top * MAX_CLUSTER_FRAC))
    kept = {}
    for k, v in clusters.items():
        if len(v) < MIN_CLUSTER:
            continue
        if len(v) > cap:
            # too broad to be a specific unmet need — that's a whole category
            print(f"  dropping cluster of {len(v)} posts (over cap {cap})")
            continue
        kept[k] = v
    return kept


def project(supply_vecs, demand_vecs, seed=42):
    import umap

    print("projecting to 3-D with UMAP…")
    combined = np.vstack([supply_vecs, demand_vecs])
    reducer = umap.UMAP(
        n_components=3, n_neighbors=25, min_dist=0.12, metric="cosine", random_state=seed
    )
    xyz = reducer.fit_transform(combined).astype(np.float32)
    xyz -= xyz.mean(axis=0)
    xyz /= np.abs(xyz).max()  # fit inside a unit cube for the renderer
    return xyz[: len(supply_vecs)], xyz[len(supply_vecs) :]


LABEL_PROMPT = """You analyze clusters of real user complaints that sit in semantic "white space" — far from any existing Y Combinator company.

For each cluster you get real post titles and the nearest YC companies by embedding similarity.

Return JSON: {"labels": [{"i": <cluster index>, "name": "<3-6 word name for the unmet need>", "thesis": "<one sentence: what these people want that nobody sells>", "why_gap": "<one sentence: what the nearest YC companies do instead, and why it doesn't cover this>"}]}

Be concrete and skeptical. If a cluster is actually well-served by the listed companies, say so plainly in why_gap rather than inventing a gap. If the posts are too incoherent to name a market, set name to "Incoherent cluster" and say so. Never invent a company or a statistic."""


def label_clusters(clusters, demand, supply, demand_vecs, supply_vecs):
    from openai import OpenAI

    load_dotenv(ROOT / ".env")
    payload = []
    nearest_by_cluster = {}

    for ci, members in clusters.items():
        centroid = demand_vecs[members].mean(axis=0)
        centroid /= np.linalg.norm(centroid)
        near = np.argsort(supply_vecs @ centroid)[::-1][:5]
        nearest_by_cluster[ci] = [int(x) for x in near]
        top_posts = sorted(members, key=lambda i: -(demand[i]["points"] or 0))[:8]
        payload.append(
            {
                "i": ci,
                "post_titles": [demand[i]["title"][:160] for i in top_posts],
                "nearest_yc": [
                    f"{supply[j]['name']}: {supply[j]['one_liner'][:110]}" for j in near
                ],
            }
        )

    resp = OpenAI().chat.completions.create(
        model=LABEL_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": LABEL_PROMPT},
            {"role": "user", "content": json.dumps({"clusters": payload})},
        ],
    )
    parsed = json.loads(resp.choices[0].message.content)
    return {int(l["i"]): l for l in parsed.get("labels", [])}, nearest_by_cluster


def dedupe_posts(member_idx, demand):
    seen, out = set(), []
    for i in member_idx:
        key = "".join(ch for ch in demand[i]["title"].lower() if ch.isalnum())[:70]
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "t": demand[i]["title"][:200],
                "u": demand[i]["url"],
                "pts": demand[i]["points"],
                "d": demand[i]["created"],
            }
        )
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--top-frac", type=float, default=0.18, help="fraction of demand considered for clustering")
    p.add_argument("--no-llm", action="store_true")
    args = p.parse_args()

    supply, demand, supply_raw, demand_raw = load()
    print(f"{len(supply)} supply, {len(demand)} demand")

    cross_before = float((demand_raw @ supply_raw.T).max(axis=1).mean())
    supply_vecs, demand_vecs = decorrelate_style(supply_raw, demand_raw)
    cross_after = float((demand_vecs @ supply_vecs.T).max(axis=1).mean())
    print(
        f"mean best demand->supply similarity: {cross_before:.3f} raw, "
        f"{cross_after:.3f} style-decorrelated"
    )

    gap, density, whitespace = score_demand(demand_vecs, supply_vecs)
    clusters = cluster_gaps(demand_vecs, whitespace, args.top_frac)
    print(f"{len(clusters)} gap clusters ({sum(len(v) for v in clusters.values())} posts)")

    labels, nearest = ({}, {})
    if not args.no_llm and clusters:
        labels, nearest = label_clusters(clusters, demand, supply, demand_vecs, supply_vecs)
        print(f"labeled {len(labels)}")

    supply_xyz, demand_xyz = project(supply_vecs, demand_vecs)

    # The labeler is instructed to flag clusters it can't name; take it at its
    # word rather than shipping "Cluster 7" onto a demo screen.
    incoherent = {
        ci
        for ci, l in labels.items()
        if "incoherent" in (l.get("name") or "").lower()
    }
    if incoherent:
        print(f"dropping {len(incoherent)} cluster(s) the labeler called incoherent")
        clusters = {k: v for k, v in clusters.items() if k not in incoherent}

    cluster_of = {}
    for ci, members in clusters.items():
        for m in members:
            cluster_of[m] = ci

    out = {
        "supply": [
            {
                "p": [round(float(v), 4) for v in supply_xyz[i]],
                "n": supply[i]["name"],
                "o": supply[i]["one_liner"][:140],
                "b": supply[i]["batch"],
            }
            for i in range(len(supply))
        ],
        "demand": [
            {
                "p": [round(float(v), 4) for v in demand_xyz[i]],
                "t": demand[i]["title"][:160],
                "u": demand[i]["url"],
                "g": round(float(whitespace[i]), 3),
                "c": cluster_of.get(i, -1),
            }
            for i in range(len(demand))
        ],
        "clusters": [
            {
                "id": ci,
                "size": len(members),
                "name": labels.get(ci, {}).get("name") or f"Cluster {ci}",
                "thesis": labels.get(ci, {}).get("thesis", ""),
                "why_gap": labels.get(ci, {}).get("why_gap", ""),
                "centroid": [
                    round(float(v), 4) for v in demand_xyz[members].mean(axis=0)
                ],
                "avg_gap": round(float(gap[members].mean()), 3),
                # HN carries reposts of the same story; showing a title twice
                # in the same panel just reads as a bug
                "posts": dedupe_posts(
                    sorted(members, key=lambda i: -(demand[i]["points"] or 0)), demand
                )[:40],
                "nearest_yc": [
                    {"n": supply[j]["name"], "o": supply[j]["one_liner"][:140]}
                    for j in nearest.get(ci, [])
                ],
            }
            for ci, members in sorted(clusters.items(), key=lambda kv: -len(kv[1]))
        ],
        "stats": {
            "supply_count": len(supply),
            "demand_count": len(demand),
            "cluster_count": len(clusters),
        },
    }

    path = DATA_DIR / "whitespace.json"
    with open(path, "w") as f:
        json.dump(out, f)
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)")
    for c in out["clusters"][:8]:
        print(f"  [{c['size']:3d} posts, gap {c['avg_gap']}] {c['name']}")


if __name__ == "__main__":
    main()
