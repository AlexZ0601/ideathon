"""Embed each researcher's recent abstracts with text-embedding-3-small.

Embeds every stored work individually (per-work vectors are what Phase 2's
evidence extraction needs) and writes:
    data/work_vecs.npy   float32 [n_works, dim], L2-normalized
    data/work_meta.json  row-aligned {researcher_id, work_id}

Requires OPENAI_API_KEY in the environment or in a .env file at the repo root.

Usage:
    python ingest/embed.py [--batch-size 64]
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODEL = "text-embedding-3-small"
TEXT_CHARS = 4000  # well under the model's 8191-token limit


def work_text(work):
    return f"{work['title']}. {work['abstract']}"[:TEXT_CHARS]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    client = OpenAI()

    with open(DATA_DIR / "researchers_raw.json") as f:
        researchers = json.load(f)["researchers"]

    texts, meta = [], []
    for r in researchers:
        for w in r["works"]:
            texts.append(work_text(w))
            meta.append({"researcher_id": r["id"], "work_id": w["id"]})

    vecs = []
    for i in tqdm(range(0, len(texts), args.batch_size), desc="batches"):
        batch = texts[i : i + args.batch_size]
        for attempt in range(5):
            try:
                resp = client.embeddings.create(model=MODEL, input=batch)
                break
            except Exception as e:
                if attempt == 4:
                    raise
                time.sleep(2**attempt)
        vecs.extend(d.embedding for d in resp.data)

    matrix = np.asarray(vecs, dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)

    np.save(DATA_DIR / "work_vecs.npy", matrix)
    with open(DATA_DIR / "work_meta.json", "w") as f:
        json.dump(meta, f)
    print(f"embedded {len(meta)} works from {len(researchers)} researchers, dim={matrix.shape[1]}")


if __name__ == "__main__":
    main()
