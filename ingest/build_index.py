"""Build the searchable index from raw researcher records + work embeddings.

Writes:
    data/index.npz         researcher_vecs (mean of work vecs, normalized),
                           researcher_ids, work_vecs, work_researcher_idx, work_ids
    data/researchers.json  metadata keyed by position in researcher_vecs

Sanity-check a query (needs OPENAI_API_KEY for query embedding):
    python ingest/build_index.py --query "our enzyme assay degrades above 40C" -k 10
"""

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def build():
    with open(DATA_DIR / "researchers_raw.json") as f:
        researchers = json.load(f)["researchers"]
    work_vecs = np.load(DATA_DIR / "work_vecs.npy")
    with open(DATA_DIR / "work_meta.json") as f:
        work_meta = json.load(f)

    row_of_researcher = {r["id"]: i for i, r in enumerate(researchers)}
    work_researcher_idx = np.array(
        [row_of_researcher[m["researcher_id"]] for m in work_meta], dtype=np.int32
    )

    researcher_vecs = np.zeros((len(researchers), work_vecs.shape[1]), dtype=np.float32)
    np.add.at(researcher_vecs, work_researcher_idx, work_vecs)
    researcher_vecs /= np.linalg.norm(researcher_vecs, axis=1, keepdims=True)

    np.savez(
        DATA_DIR / "index.npz",
        researcher_vecs=researcher_vecs,
        researcher_ids=np.array([r["id"] for r in researchers]),
        work_vecs=work_vecs,
        work_researcher_idx=work_researcher_idx,
        work_ids=np.array([m["work_id"] for m in work_meta]),
    )
    with open(DATA_DIR / "researchers.json", "w") as f:
        json.dump(researchers, f)
    print(f"index: {len(researchers)} researchers, {len(work_meta)} work vectors")


def query(text, k):
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(ROOT / ".env")
    resp = OpenAI().embeddings.create(model="text-embedding-3-small", input=[text])
    qvec = np.asarray(resp.data[0].embedding, dtype=np.float32)
    qvec /= np.linalg.norm(qvec)

    index = np.load(DATA_DIR / "index.npz")
    with open(DATA_DIR / "researchers.json") as f:
        researchers = json.load(f)

    scores = index["researcher_vecs"] @ qvec
    work_scores = index["work_vecs"] @ qvec
    for rank, i in enumerate(np.argsort(scores)[::-1][:k], 1):
        r = researchers[i]
        # best individual work is the evidence, not the aggregate score
        rows = np.flatnonzero(index["work_researcher_idx"] == i)
        best = r["works"][int(np.argmax(work_scores[rows]))]
        print(f"{rank:2d}. {r['name']}  [{r['dept']}]  sim={scores[i]:.3f}")
        print(f"    best match: \"{best['title']}\" ({best['year']})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", help="skip build; run a test query against the index")
    parser.add_argument("-k", type=int, default=10)
    args = parser.parse_args()
    if args.query:
        query(args.query, args.k)
    else:
        build()


if __name__ == "__main__":
    main()
