"""ResearchBridge web app: FastAPI backend + static swipe UI.

Match results are cached to data/cache/ keyed by query, so a repeated demo
query costs nothing and returns instantly — and so the demo survives a dead
network for anything already run once.

Usage:
    .venv/bin/uvicorn app.server:app --reload --port 8000
"""

import hashlib
import json
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import intro as intro_mod  # noqa: E402
from api import match as match_mod  # noqa: E402

CACHE_DIR = ROOT / "data" / "cache"
STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="ResearchBridge")

SCENARIOS = [
    {
        "label": "Enzyme stability",
        "text": "Our assay degrades above 40C and we can't keep the enzyme stable long enough for a field-deployable diagnostic.",
    },
    {
        "label": "Inference latency",
        "text": "We need to cut transformer inference latency for real-time serving without buying more GPUs.",
    },
    {
        "label": "Battery degradation",
        "text": "Our lithium-ion cathode loses capacity after a few hundred charge cycles and we don't know which failure mode dominates.",
    },
    {
        "label": "Water sensing",
        "text": "We want a cheap sensor that detects bacterial contamination in rural water supplies without lab equipment.",
    },
]


class MatchRequest(BaseModel):
    problem: str
    major: str | None = None
    k: int = 12
    refresh: bool = False


class Founder(BaseModel):
    name: str = "a Princeton undergraduate"
    year: str = "junior"
    major: str | None = None
    project: str | None = None


class IntroRequest(BaseModel):
    researcher_id: str
    work_id: str | None = None
    problem: str
    founder: Founder = Founder()


def cache_path(req: MatchRequest) -> Path:
    key = hashlib.sha256(
        json.dumps([req.problem.strip().lower(), req.major, req.k]).encode()
    ).hexdigest()[:16]
    return CACHE_DIR / f"match_{key}.json"


@app.get("/api/scenarios")
def scenarios():
    return {"scenarios": SCENARIOS}


@app.post("/api/match")
def api_match(req: MatchRequest):
    if not req.problem.strip():
        raise HTTPException(400, "problem text is required")

    path = cache_path(req)
    if path.exists() and not req.refresh:
        with open(path) as f:
            return {"cached": True, **json.load(f)}

    matches = match_mod.match(req.problem, k=req.k, major=req.major)
    try:
        matches = match_mod.add_rationales(req.problem, matches)
    except Exception as e:
        # A rationale failure must not cost the user their matches; the cards
        # still carry the cited paper, which is the load-bearing evidence.
        print(f"rationale generation failed: {e}", file=sys.stderr)

    payload = {"problem": req.problem, "matches": matches}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)
    return {"cached": False, **payload}


@app.post("/api/intro")
def api_intro(req: IntroRequest):
    researchers = intro_mod.load_researchers()
    researcher, work = intro_mod.find(researchers, req.researcher_id, req.work_id)
    email = intro_mod.draft(researcher, work, req.problem, req.founder.model_dump())
    return {"researcher": researcher["name"], **email}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
