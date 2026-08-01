"""Cofoundr web app: FastAPI backend + static swipe UI.

Match results are cached to data/cache/ keyed by query, so a repeated demo
query costs nothing and returns instantly — and so the demo survives a dead
network for anything already run once.

Usage:
    .venv/bin/uvicorn app.server:app --reload --port 8000
"""

import hashlib
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import auth as auth_mod  # noqa: E402
from api import intro as intro_mod  # noqa: E402
from api import match as match_mod  # noqa: E402
from api import resume as resume_mod  # noqa: E402
from api import store  # noqa: E402
from api import translate as translate_mod  # noqa: E402

CACHE_DIR = ROOT / "data" / "cache"
STATIC = Path(__file__).resolve().parent / "static"
NO_CACHE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}

app = FastAPI(title="Cofoundr")

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
    refresh: bool = False


def cache_path(req: MatchRequest, seeking=None) -> Path:
    # seeking flips the seniority direction, so it changes the results and
    # therefore has to be part of the key
    key = hashlib.sha256(
        json.dumps(
            [req.problem.strip().lower(), req.major, req.k, sorted(seeking or [])]
        ).encode()
    ).hexdigest()[:16]
    return CACHE_DIR / f"match_{key}.json"


def intro_cache_path(req: IntroRequest) -> Path:
    key = hashlib.sha256(
        json.dumps(
            [
                req.problem.strip().lower(),
                req.researcher_id,
                req.work_id,
                sorted(req.founder.model_dump().items()),
            ]
        ).encode()
    ).hexdigest()[:16]
    return CACHE_DIR / f"intro_{key}.json"


def current_user(rb_session: str | None = Cookie(default=None)):
    """Resolved user or None. Use require_user() when the route needs one."""
    uid = auth_mod.read_token(rb_session)
    return store.user_by_id(uid) if uid else None


def require_user(user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "Sign in first.")
    return user


@app.get("/api/scenarios")
def scenarios():
    return {"scenarios": SCENARIOS}


@app.post("/api/match")
def api_match(req: MatchRequest, user=Depends(current_user)):
    if not req.problem.strip():
        raise HTTPException(400, "problem text is required")

    seeking = store.get_seeking(user) if user else []
    path = cache_path(req, seeking)
    if path.exists() and not req.refresh:
        with open(path) as f:
            return {"cached": True, **json.load(f)}

    matches = match_mod.match(req.problem, k=req.k, major=req.major, seeking=seeking)
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
def api_intro(req: IntroRequest, user=Depends(current_user)):
    founder = req.founder.model_dump()
    # a signed-in founder's saved profile beats whatever the anonymous form had
    if user and user["role"] == "founder":
        p = store.get_founder_profile(user["id"])
        founder = {
            "name": user["name"],
            "year": p.get("year") or founder.get("year"),
            "major": p.get("major") or founder.get("major"),
            "project": p.get("project") or founder.get("project"),
            "resume_text": p.get("resume_text"),
        }

    path = intro_cache_path(req)
    # a resume makes the draft personal, so the shared cache no longer applies
    use_cache = not founder.get("resume_text")
    if use_cache and path.exists() and not req.refresh:
        with open(path) as f:
            return {"cached": True, **json.load(f)}

    researchers = intro_mod.load_researchers()
    researcher, work = intro_mod.find(researchers, req.researcher_id, req.work_id)
    email = intro_mod.draft(researcher, work, req.problem, founder)

    payload = {"researcher": researcher["name"], **email}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)
    return {"cached": False, **payload}


# ── accounts ───────────────────────────────────────────

def public_user(user):
    """Everything the client may see about the signed-in account."""
    out = {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "identity": user.get("identity"),
        "seeking": store.get_seeking(user),
        "accepted_terms": bool(user.get("accepted_terms")),
        "unread": store.unread_count(user["id"]),
    }
    if user["role"] == "founder":
        p = store.get_founder_profile(user["id"])
        out["profile"] = {
            "year": p.get("year"),
            "major": p.get("major"),
            "project": p.get("project"),
            "bio": p.get("bio"),
            "school": p.get("school"),
            "org": p.get("org"),
            "looking": p.get("looking"),
            "website": p.get("website"),
            "github": p.get("github"),
            "linkedin": p.get("linkedin"),
            "skills": p.get("skills"),
            "stage": p.get("stage"),
            "commitment": p.get("commitment"),
            "resume_name": p.get("resume_name"),
            # the parsed text can run to 20k chars; the client only needs to
            # know whether it exists and roughly how much was read
            "resume_chars": len(p.get("resume_text") or ""),
        }
    else:
        claim = store.get_claim(user["id"])
        out["claim"] = None
        if claim:
            r = match_mod.researcher_by_id(claim["researcher_id"])
            out["claim"] = {
                "researcher_id": claim["researcher_id"],
                "accepting": bool(claim["accepting"]),
                "note": claim["note"],
                "name": (r or {}).get("name"),
                "dept": (r or {}).get("dept"),
                "works": len((r or {}).get("works") or []),
            }
    return out


IDENTITIES = {
    "founder": "Founder / building something",
    "researcher": "Researcher / professor",
    "technical": "Technical person looking for a role",
    "student": "Student looking for research or a mentor",
    "other": "Something else",
}

SEEKING = {
    "professor": "A professor or PI",
    "researcher": "A researcher with specific expertise",
    "cofounder": "A co-founder or technical partner",
    "employee": "Someone to hire",
    "advisor": "An advisor or mentor",
    "collaborator": "A research collaborator",
}


class SignupRequest(BaseModel):
    email: str
    password: str
    name: str
    role: str = "founder"
    identity: str | None = None
    seeking: list[str] = []
    accept_terms: bool = False


class LoginRequest(BaseModel):
    email: str
    password: str


def _set_session(response: Response, user_id: int):
    response.set_cookie(
        auth_mod.COOKIE_NAME,
        auth_mod.issue_token(user_id),
        max_age=auth_mod.SESSION_TTL,
        httponly=True,
        samesite="lax",
    )


@app.post("/api/auth/signup")
def api_signup(req: SignupRequest, response: Response):
    if req.role not in ("founder", "researcher"):
        raise HTTPException(400, "role must be founder or researcher")
    for problem in (auth_mod.email_problem(req.email), auth_mod.password_problem(req.password)):
        if problem:
            raise HTTPException(400, problem)
    if not req.name.strip():
        raise HTTPException(400, "Enter your name.")
    if not req.accept_terms:
        raise HTTPException(400, "You need to accept the terms to create an account.")
    if req.identity and req.identity not in IDENTITIES:
        raise HTTPException(400, "Unknown identity option.")
    bad = [s for s in req.seeking if s not in SEEKING]
    if bad:
        raise HTTPException(400, f"Unknown seeking option: {bad[0]}")
    if store.user_by_email(req.email):
        raise HTTPException(409, "An account with that email already exists.")

    uid = store.create_user(
        req.email, auth_mod.hash_password(req.password), req.role, req.name
    )
    store.set_intake(
        uid, identity=req.identity, seeking=req.seeking, accepted_terms=True
    )
    _set_session(response, uid)
    return public_user(store.user_by_id(uid))


@app.post("/api/auth/login")
def api_login(req: LoginRequest, response: Response):
    user = store.user_by_email(req.email)
    # same message either way: don't leak which emails have accounts
    if not user or not auth_mod.verify_password(req.password, user["pw_hash"]):
        raise HTTPException(401, "Email or password is incorrect.")
    _set_session(response, user["id"])
    return public_user(user)


@app.post("/api/auth/logout")
def api_logout(response: Response):
    response.delete_cookie(auth_mod.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def api_me(user=Depends(current_user)):
    return {"user": public_user(user) if user else None}


class ProfileRequest(BaseModel):
    year: str | None = None
    major: str | None = None
    project: str | None = None
    bio: str | None = None
    school: str | None = None
    org: str | None = None
    looking: bool | None = None
    website: str | None = None
    github: str | None = None
    linkedin: str | None = None
    skills: str | None = None
    stage: str | None = None
    commitment: str | None = None


class PasswordRequest(BaseModel):
    current: str
    new_password: str


@app.post("/api/account/password")
def api_password(req: PasswordRequest, user=Depends(require_user)):
    if not auth_mod.verify_password(req.current, user["pw_hash"]):
        raise HTTPException(403, "Current password is incorrect.")
    problem = auth_mod.password_problem(req.new_password)
    if problem:
        raise HTTPException(400, problem)
    store.change_password(user["id"], auth_mod.hash_password(req.new_password))
    return {"ok": True}


@app.get("/api/account/export")
def api_export(user=Depends(require_user)):
    return store.export_account(user["id"])


class DeleteRequest(BaseModel):
    confirm: str


@app.post("/api/account/delete")
def api_delete(req: DeleteRequest, response: Response, user=Depends(require_user)):
    # typed confirmation, because this is irreversible and one stray click away
    if req.confirm.strip().upper() != "DELETE":
        raise HTTPException(400, 'Type DELETE to confirm.')
    store.delete_account(user["id"])
    response.delete_cookie(auth_mod.COOKIE_NAME)
    return {"ok": True}


@app.put("/api/profile")
def api_profile(req: ProfileRequest, user=Depends(require_user)):
    if user["role"] != "founder":
        raise HTTPException(403, "Only founder accounts have this profile.")
    fields = req.model_dump(exclude_none=True)
    if "looking" in fields:
        fields["looking"] = 1 if fields["looking"] else 0
    store.upsert_founder_profile(user["id"], **fields)
    return public_user(store.user_by_id(user["id"]))


# ── researcher directory ───────────────────────────────

@lru_cache(maxsize=1)
def _dept_facets():
    counts = {}
    for r in match_mod.load_index()["researchers"]:
        if r["dept"]:
            counts[r["dept"]] = counts.get(r["dept"], 0) + 1
    return sorted(
        ({"name": k, "count": v} for k, v in counts.items()), key=lambda x: -x["count"]
    )


@app.get("/api/researchers/browse")
def api_browse(
    q: str | None = None,
    dept: str | None = None,
    seniority: str | None = None,
    offset: int = 0,
    limit: int = 24,
):
    """Browse the whole indexed directory, not just search results.

    This is the professor-side counterpart to the cofounder hub — except it
    isn't cold-start limited, because all 4,159 are already here from public
    data. Nobody had to sign up for this page to have something on it.
    """
    rows = match_mod.load_index()["researchers"]
    needle = (q or "").strip().lower()

    out = []
    for r in rows:
        if dept and r["dept"] != dept:
            continue
        if seniority == "pi" and (r.get("seniority") or 0) < 0.5:
            continue
        if seniority == "early" and (r.get("seniority") or 0) >= 0.25:
            continue
        if needle:
            hay = f"{r['name']} {r['dept'] or ''} {' '.join(r['tags'] or [])}".lower()
            if needle not in hay:
                continue
        out.append(r)

    out.sort(key=lambda r: -r["works_count_recent"])
    total = len(out)
    page = out[offset : offset + limit]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
        "facets": {"depts": _dept_facets()[:24]},
        "researchers": [
            {
                "researcher_id": r["id"],
                "name": r["name"],
                "dept": r["dept"],
                "tags": r["tags"],
                "works": r["works_count_recent"],
                "seniority": r.get("seniority"),
                "h_index": (r.get("author_stats") or {}).get("h_index"),
                "recent": strip_tags((r["works"][0] or {}).get("title", ""))[:130],
                "claimed": bool(store.claim_owner(r["id"])),
            }
            for r in page
        ],
    }


# ── cofounder hub ──────────────────────────────────────

@app.get("/api/hub")
def api_hub(
    q: str | None = None,
    school: str | None = None,
    org: str | None = None,
    user=Depends(current_user),
):
    """Search people who signed up and left themselves visible.

    Deliberately not the researcher index: those 4,159 never consented to being
    contacted as potential cofounders. This side is opt-in only, which is why
    it starts empty and the UI says so instead of padding it out.
    """
    people = store.hub_search(
        q=q, school=school, org=org, exclude_uid=user["id"] if user else None
    )
    return {
        "people": people,
        "facets": store.hub_facets(),
        "signed_in": bool(user),
        "total": len(people),
    }


@app.post("/api/resume")
async def api_resume(file: UploadFile = File(...), user=Depends(require_user)):
    if user["role"] != "founder":
        raise HTTPException(403, "Only founder accounts can upload a resume.")
    try:
        text = resume_mod.extract(file.filename, await file.read())
    except resume_mod.ResumeError as e:
        raise HTTPException(400, str(e))
    store.set_resume(user["id"], file.filename, text)
    return {"resume_name": file.filename, "resume_chars": len(text), "excerpt": text[:400]}


@app.get("/api/options")
def api_options():
    return {
        "identities": [{"id": k, "label": v} for k, v in IDENTITIES.items()],
        "seeking": [{"id": k, "label": v} for k, v in SEEKING.items()],
    }


class IntakeRequest(BaseModel):
    identity: str | None = None
    seeking: list[str] | None = None


@app.put("/api/intake")
def api_intake(req: IntakeRequest, user=Depends(require_user)):
    if req.identity and req.identity not in IDENTITIES:
        raise HTTPException(400, "Unknown identity option.")
    if req.seeking is not None:
        bad = [s for s in req.seeking if s not in SEEKING]
        if bad:
            raise HTTPException(400, f"Unknown seeking option: {bad[0]}")
    store.set_intake(user["id"], identity=req.identity, seeking=req.seeking)
    return public_user(store.user_by_id(user["id"]))


@app.get("/api/members")
def api_members(user=Depends(require_user)):
    """People with accounts here — the genuinely cold-start side.

    Kept deliberately separate from /api/match: that searches 4,159 researchers
    built from public data, this searches everyone who has signed up. Conflating
    them would hide which half of the product actually has supply.
    """
    people = store.members(exclude_uid=user["id"])
    return {
        "members": people,
        "note": (
            "These are people who signed up. Unlike the researcher index — which "
            "had 4,159 people in it before anyone joined — this side starts empty "
            "and fills in as the community grows."
        ),
    }


class TranslateRequest(BaseModel):
    body: str
    subject: str | None = None


@app.post("/api/translate")
def api_translate(req: TranslateRequest, user=Depends(require_user)):
    if not req.body.strip():
        raise HTTPException(400, "Nothing to translate.")
    try:
        return translate_mod.translate(req.body, req.subject)
    except Exception as e:
        raise HTTPException(502, f"Translation failed: {e}")


# ── researcher claim ───────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(s):
    """OpenAlex titles carry markup like <i>Ab Initio</i>."""
    return _TAG_RE.sub("", s or "")

@app.get("/api/researchers/search")
def api_researcher_search(q: str, limit: int = 8):
    """Name search so a professor can find the profile that already exists."""
    if len(q.strip()) < 2:
        return {"results": []}
    needle = q.strip().lower()

    def rank(name):
        """Lower is better. A plain substring test puts 'Annabella Selloni'
        ahead of 'A. Bell' for the query 'Bell', which is useless to someone
        trying to find themselves."""
        low = (name or "").lower()
        words = low.replace(".", " ").replace("-", " ").split()
        if low == needle:
            return 0
        if needle in words:
            return 1
        if any(w.startswith(needle) for w in words):
            return 2
        if needle in low:
            return 4
        return None

    scored = []
    for r in match_mod.load_index()["researchers"]:
        score = rank(r["name"])
        if score is not None:
            scored.append((score, -r["works_count_recent"], r))
    scored.sort(key=lambda t: (t[0], t[1]))

    out = []
    for _, _, r in scored[:limit]:
        owner = store.claim_owner(r["id"])
        out.append(
            {
                "researcher_id": r["id"],
                "name": r["name"],
                "dept": r["dept"],
                "works": r["works_count_recent"],
                "recent": [strip_tags(w["title"])[:120] for w in r["works"][:3]],
                "claimed": bool(owner),
                "pending": store.pending_for_researcher(r["id"]),
            }
        )
    return {"results": out}


class ClaimRequest(BaseModel):
    researcher_id: str


@app.post("/api/claim")
def api_claim(req: ClaimRequest, user=Depends(require_user)):
    if user["role"] != "researcher":
        raise HTTPException(403, "Only researcher accounts can claim a profile.")
    if store.get_claim(user["id"]):
        raise HTTPException(409, "This account has already claimed a profile.")
    if store.claim_owner(req.researcher_id):
        raise HTTPException(409, "Someone has already claimed that profile.")
    if not match_mod.researcher_by_id(req.researcher_id):
        raise HTTPException(404, "No researcher with that id.")
    store.create_claim(user["id"], req.researcher_id)
    return public_user(store.user_by_id(user["id"]))


class AcceptingRequest(BaseModel):
    accepting: bool
    note: str | None = None


@app.put("/api/claim/accepting")
def api_accepting(req: AcceptingRequest, user=Depends(require_user)):
    if not store.get_claim(user["id"]):
        raise HTTPException(404, "Claim a profile first.")
    store.set_accepting(user["id"], req.accepting, req.note)
    return public_user(store.user_by_id(user["id"]))


# ── messages ───────────────────────────────────────────

class MessageRequest(BaseModel):
    researcher_id: str | None = None
    to_user_id: int | None = None     # cofounder hub: message another member
    thread_id: int | None = None
    subject: str | None = None
    body: str
    paper_title: str | None = None


@app.post("/api/messages")
def api_send(req: MessageRequest, user=Depends(require_user)):
    if not req.body.strip():
        raise HTTPException(400, "Message body is empty.")

    if req.thread_id:
        existing = store.thread(req.thread_id, user["id"])
        if not existing:
            raise HTTPException(404, "No such thread.")
        first = existing[0]
        # reply goes to whoever on the thread isn't you
        other = first["to_user"] if first["from_user"] == user["id"] else first["from_user"]
        store.send_message(
            user["id"],
            req.subject or f"Re: {first['subject']}",
            req.body,
            to_user=other,
            to_researcher=None if other else first["to_researcher"],
            thread_id=req.thread_id,
        )
        return {"ok": True, "thread_id": req.thread_id}

    if req.to_user_id:
        target = store.user_by_id(req.to_user_id)
        if not target:
            raise HTTPException(404, "No such member.")
        if target["id"] == user["id"]:
            raise HTTPException(400, "That's you.")
        mid = store.send_message(
            user["id"], req.subject or "Intro", req.body, to_user=target["id"]
        )
        return {
            "ok": True,
            "thread_id": mid,
            "delivered_in_app": True,
            "researcher_name": target["name"],
            "notice": f"Sent to {target['name']} — it's in their cofoundr inbox.",
        }

    if not req.researcher_id:
        raise HTTPException(400, "researcher_id or thread_id is required.")
    researcher = match_mod.researcher_by_id(req.researcher_id)
    if not researcher:
        raise HTTPException(404, "No researcher with that id.")

    owner = store.claim_owner(req.researcher_id)
    mid = store.send_message(
        user["id"],
        req.subject or "Intro",
        req.body,
        to_user=owner["id"] if owner else None,
        to_researcher=None if owner else req.researcher_id,
        paper_title=req.paper_title,
    )
    return {
        "ok": True,
        "thread_id": mid,
        "delivered_in_app": bool(owner),
        "researcher_name": researcher["name"],
        # the honest bit: most researchers have not claimed a profile, so this
        # is a draft the founder still has to send by email
        "notice": (
            f"{researcher['name']} is on Cofoundr — they'll see this in their inbox."
            if owner
            else f"{researcher['name']} hasn't claimed their profile yet. This is saved in "
            "your sent folder; copy it into an email to actually reach them."
        ),
    }


@app.get("/api/messages")
def api_messages(user=Depends(require_user)):
    return {
        "inbox": store.inbox(user["id"]),
        "sent": store.sent(user["id"]),
        "unread": store.unread_count(user["id"]),
    }


@app.get("/api/messages/{thread_id}")
def api_thread(thread_id: int, user=Depends(require_user)):
    msgs = store.thread(thread_id, user["id"])
    if msgs is None:
        raise HTTPException(404, "No such thread.")
    store.mark_read(thread_id, user["id"])
    return {"messages": msgs}


@app.get("/api/terms")
def api_terms():
    return FileResponse(STATIC / "terms.html", media_type="text/html", headers=NO_CACHE)


class PositionRequest(BaseModel):
    problem: str


@app.post("/api/whitespace/position")
def api_position(req: PositionRequest):
    """Where does this idea sit relative to what's already funded?

    Closes the loop between the two halves of the app: the map finds open
    territory, and this tells a founder whether the thing they're already
    building is standing in it or in a crowd. Uses the same style-decorrelated
    space the gap scores were computed in, so the numbers are comparable.
    """
    import numpy as np

    path = ROOT / "data" / "ws_vecs.npz"
    if not path.exists():
        raise HTTPException(404, "White Space vectors missing — run ingest/whitespace.py")

    z = np.load(path)
    supply_raw, demand_raw = z["supply_vecs"], z["demand_vecs"]

    sys.path.insert(0, str(ROOT))
    from ingest.whitespace_map import decorrelate_style

    supply, demand = decorrelate_style(supply_raw, demand_raw)

    qv = match_mod.embed_query(req.problem)
    # project the query into the same centred space as the corpora
    q_s = qv - supply_raw.mean(axis=0)
    q_s /= np.linalg.norm(q_s) + 1e-9
    q_d = qv - demand_raw.mean(axis=0)
    q_d /= np.linalg.norm(q_d) + 1e-9

    sup_sims = supply @ q_s.astype("float32")
    dem_sims = demand @ q_d.astype("float32")

    with open(ROOT / "data" / "ws_supply.json") as f:
        supply_meta = json.load(f)
    with open(ROOT / "data" / "ws_demand.json") as f:
        demand_meta = json.load(f)

    top_sup = np.argsort(sup_sims)[::-1][:6]
    top_dem = np.argsort(dem_sims)[::-1][:6]

    crowding = float(np.sort(sup_sims)[::-1][:8].mean())
    demand_pull = float(np.sort(dem_sims)[::-1][:8].mean())

    if crowding > 0.42:
        verdict = "Crowded. Several funded companies sit close to this."
    elif crowding > 0.30:
        verdict = "Contested. There's adjacent funded work, but nothing dead-on."
    else:
        verdict = "Open. Nothing funded sits especially close to this."

    return {
        "crowding": round(crowding, 3),
        "demand_pull": round(demand_pull, 3),
        "verdict": verdict,
        "nearest_companies": [
            {
                "name": supply_meta[int(i)]["name"],
                "one_liner": supply_meta[int(i)]["one_liner"],
                "batch": supply_meta[int(i)]["batch"],
                "sim": round(float(sup_sims[int(i)]), 3),
            }
            for i in top_sup
        ],
        "nearest_demand": [
            {
                "title": demand_meta[int(i)]["title"],
                "url": demand_meta[int(i)]["url"],
                "sim": round(float(dem_sims[int(i)]), 3),
            }
            for i in top_dem
        ],
    }


@app.get("/api/whitespace")
def api_whitespace():
    path = ROOT / "data" / "whitespace.json"
    if not path.exists():
        raise HTTPException(
            404, "whitespace.json missing — run ingest/whitespace.py then ingest/whitespace_map.py"
        )
    return FileResponse(path, media_type="application/json")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers=NO_CACHE)


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Serve assets uncached.

    A stale style.css after an edit looks exactly like a broken change, and
    debugging that at 7pm on demo day is a bad use of the evening. Localhost
    has no bandwidth problem worth trading for it.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers.update(NO_CACHE)
    return response


app.mount("/static", StaticFiles(directory=STATIC), name="static")
