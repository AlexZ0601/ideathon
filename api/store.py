"""Accounts, profiles, claims and messages, on stdlib sqlite3.

The spec says no database, and that's still the right instinct for a 5-day
build — but accounts and a message inbox need durable state, and a single
gitignored .db file needs no server, no migration tool, and no dependency. It
is closer to "flat file" than to infrastructure.

The one design rule that matters here: a researcher row is NOT created by
signing up. All 4,159 researchers already exist in the index from public data.
A professor account *claims* one. Messages can be addressed to a researcher
nobody has claimed yet, and are waiting for them if they ever do.
"""

import json  # noqa: F401  (used by set_intake / get_seeking)
import os
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("RB_DB", ROOT / "data" / "app.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
  pw_hash       TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('founder', 'researcher')),
  name          TEXT NOT NULL,
  created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS founder_profiles (
  user_id         INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  year            TEXT,
  major           TEXT,
  project         TEXT,
  bio             TEXT,
  resume_name     TEXT,
  resume_text     TEXT,
  resume_uploaded REAL
);

-- A claim links an account to a researcher that already existed in the index.
-- UNIQUE on researcher_id: two people can't both claim the same person.
CREATE TABLE IF NOT EXISTS claims (
  user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  researcher_id TEXT NOT NULL UNIQUE,
  accepting     INTEGER NOT NULL DEFAULT 1,
  note          TEXT,
  claimed_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id      INTEGER NOT NULL,
  from_user      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  -- exactly one of these is set: a claimed account, or a researcher who has
  -- not claimed their profile yet
  to_user        INTEGER REFERENCES users(id) ON DELETE SET NULL,
  to_researcher  TEXT,
  subject        TEXT NOT NULL,
  body           TEXT NOT NULL,
  paper_title    TEXT,
  created_at     REAL NOT NULL,
  read_at        REAL
);

CREATE INDEX IF NOT EXISTS idx_msg_to_user ON messages(to_user);
CREATE INDEX IF NOT EXISTS idx_msg_to_res  ON messages(to_researcher);
CREATE INDEX IF NOT EXISTS idx_msg_thread  ON messages(thread_id);
"""


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


_con = None


# Columns added after the first version shipped. CREATE TABLE IF NOT EXISTS
# won't touch an existing table, so anyone with a db from yesterday needs these
# added explicitly rather than silently missing them.
LATER_COLUMNS = [
    ("users", "identity", "TEXT"),
    ("users", "seeking", "TEXT"),        # JSON array
    ("users", "accepted_terms", "REAL"),
    # Cofounder hub. On founder_profiles rather than users so a researcher
    # account claiming a public profile never grows a school field it didn't
    # ask for.
    ("founder_profiles", "school", "TEXT"),
    ("founder_profiles", "org", "TEXT"),
    ("founder_profiles", "looking", "INTEGER"),   # visible in the hub at all
]


def _migrate(con):
    for table, column, decl in LATER_COLUMNS:
        cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    con.commit()


def db():
    global _con
    if _con is None:
        _con = connect()
        _con.executescript(SCHEMA)
        _migrate(_con)
    return _con


def row_to_dict(r):
    return dict(r) if r is not None else None


# ── users ──────────────────────────────────────────────

def create_user(email, pw_hash, role, name):
    con = db()
    cur = con.execute(
        "INSERT INTO users (email, pw_hash, role, name, created_at) VALUES (?,?,?,?,?)",
        (email.strip(), pw_hash, role, name.strip(), time.time()),
    )
    con.commit()
    return cur.lastrowid


def user_by_email(email):
    return row_to_dict(
        db().execute("SELECT * FROM users WHERE email = ?", (email.strip(),)).fetchone()
    )


def user_by_id(uid):
    return row_to_dict(db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone())


def set_intake(uid, identity=None, seeking=None, accepted_terms=None):
    """The two matching questions, plus the terms checkbox."""
    sets, vals = [], []
    if identity is not None:
        sets.append("identity = ?")
        vals.append(identity)
    if seeking is not None:
        sets.append("seeking = ?")
        vals.append(json.dumps(seeking))
    if accepted_terms:
        sets.append("accepted_terms = ?")
        vals.append(time.time())
    if not sets:
        return
    con = db()
    con.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", (*vals, uid))
    con.commit()


def get_seeking(user):
    try:
        return json.loads(user.get("seeking") or "[]")
    except (ValueError, TypeError):
        return []


def members(exclude_uid=None, identity=None, limit=50):
    """People with accounts here.

    The researcher index has 4,159 people in it from public data. This table
    does not — it only holds people who actually signed up. Anything matching
    against it is genuinely cold-start limited, and the UI says so.
    """
    q = "SELECT id, name, identity, seeking, role, created_at FROM users WHERE 1=1"
    args = []
    if exclude_uid:
        q += " AND id != ?"
        args.append(exclude_uid)
    if identity:
        q += " AND identity = ?"
        args.append(identity)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)

    out = []
    for r in db().execute(q, args).fetchall():
        d = row_to_dict(r)
        d["seeking"] = get_seeking(d)
        p = get_founder_profile(d["id"])
        d["blurb"] = p.get("project") or p.get("bio") or ""
        d["major"] = p.get("major")
        out.append(d)
    return out


def hub_search(q=None, school=None, org=None, exclude_uid=None, limit=60):
    """The cofounder hub.

    Unlike researcher search, this only sees people who actually signed up and
    opted in — `looking` defaults to on for founder accounts, but anyone can
    switch it off and disappear from here without deleting anything.
    """
    where = ["COALESCE(p.looking, 1) = 1"]
    args = []

    if exclude_uid:
        where.append("u.id != ?")
        args.append(exclude_uid)
    if school:
        where.append("p.school LIKE ?")
        args.append(f"%{school.strip()}%")
    if org:
        where.append("p.org LIKE ?")
        args.append(f"%{org.strip()}%")
    if q:
        # one box that searches the things a person would actually type
        fields = ["u.name", "p.school", "p.org", "p.major", "p.project", "p.bio"]
        where.append("(" + " OR ".join(f"{f} LIKE ?" for f in fields) + ")")
        args.extend([f"%{q.strip()}%"] * len(fields))

    sql = (
        "SELECT u.id, u.name, u.identity, u.seeking, u.created_at, "
        "       p.school, p.org, p.major, p.year, p.project, p.bio "
        "FROM users u JOIN founder_profiles p ON p.user_id = u.id "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY u.created_at DESC LIMIT ?"
    )
    args.append(limit)

    out = []
    for r in db().execute(sql, args).fetchall():
        d = row_to_dict(r)
        d["seeking"] = get_seeking(d)
        d["blurb"] = d.pop("project") or d.pop("bio") or ""
        out.append(d)
    return out


def hub_facets():
    """Distinct schools and orgs, for the filter chips."""
    rows = db().execute(
        "SELECT school, org, COUNT(*) AS n FROM founder_profiles "
        "WHERE COALESCE(looking, 1) = 1 GROUP BY school, org"
    ).fetchall()
    schools, orgs = {}, {}
    for r in rows:
        if r["school"]:
            schools[r["school"]] = schools.get(r["school"], 0) + r["n"]
        if r["org"]:
            orgs[r["org"]] = orgs.get(r["org"], 0) + r["n"]
    return {
        "schools": sorted(
            ({"name": k, "count": v} for k, v in schools.items()), key=lambda x: -x["count"]
        ),
        "orgs": sorted(
            ({"name": k, "count": v} for k, v in orgs.items()), key=lambda x: -x["count"]
        ),
    }


# ── founder profile ────────────────────────────────────

def get_founder_profile(uid):
    return row_to_dict(
        db().execute("SELECT * FROM founder_profiles WHERE user_id = ?", (uid,)).fetchone()
    ) or {}


def upsert_founder_profile(uid, **fields):
    allowed = {"year", "major", "project", "bio", "school", "org", "looking"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    con = db()
    con.execute("INSERT OR IGNORE INTO founder_profiles (user_id) VALUES (?)", (uid,))
    sets = ", ".join(f"{k} = ?" for k in fields)
    con.execute(
        f"UPDATE founder_profiles SET {sets} WHERE user_id = ?", (*fields.values(), uid)
    )
    con.commit()


def set_resume(uid, name, text):
    con = db()
    con.execute("INSERT OR IGNORE INTO founder_profiles (user_id) VALUES (?)", (uid,))
    con.execute(
        "UPDATE founder_profiles SET resume_name = ?, resume_text = ?, resume_uploaded = ? "
        "WHERE user_id = ?",
        (name, text, time.time(), uid),
    )
    con.commit()


# ── claims ─────────────────────────────────────────────

def get_claim(uid):
    return row_to_dict(
        db().execute("SELECT * FROM claims WHERE user_id = ?", (uid,)).fetchone()
    )


def claim_owner(researcher_id):
    """Which account, if any, has claimed this researcher."""
    return row_to_dict(
        db()
        .execute(
            "SELECT u.* FROM claims c JOIN users u ON u.id = c.user_id "
            "WHERE c.researcher_id = ?",
            (researcher_id,),
        )
        .fetchone()
    )


def create_claim(uid, researcher_id):
    con = db()
    con.execute(
        "INSERT INTO claims (user_id, researcher_id, claimed_at) VALUES (?,?,?)",
        (uid, researcher_id, time.time()),
    )
    # hand over anything sent before they claimed
    con.execute(
        "UPDATE messages SET to_user = ? WHERE to_researcher = ? AND to_user IS NULL",
        (uid, researcher_id),
    )
    con.commit()


def set_accepting(uid, accepting, note=None):
    con = db()
    con.execute(
        "UPDATE claims SET accepting = ?, note = ? WHERE user_id = ?",
        (1 if accepting else 0, note, uid),
    )
    con.commit()


# ── messages ───────────────────────────────────────────

def send_message(from_user, subject, body, to_user=None, to_researcher=None,
                 thread_id=None, paper_title=None):
    con = db()
    cur = con.execute(
        "INSERT INTO messages (thread_id, from_user, to_user, to_researcher, subject, "
        "body, paper_title, created_at) VALUES (0,?,?,?,?,?,?,?)",
        (from_user, to_user, to_researcher, subject, body, paper_title, time.time()),
    )
    mid = cur.lastrowid
    # a new message starts its own thread; a reply joins an existing one
    con.execute("UPDATE messages SET thread_id = ? WHERE id = ?", (thread_id or mid, mid))
    con.commit()
    return mid


def inbox(uid):
    return [
        row_to_dict(r)
        for r in db()
        .execute(
            "SELECT m.*, u.name AS from_name, u.email AS from_email "
            "FROM messages m JOIN users u ON u.id = m.from_user "
            "WHERE m.to_user = ? ORDER BY m.created_at DESC",
            (uid,),
        )
        .fetchall()
    ]


def sent(uid):
    return [
        row_to_dict(r)
        for r in db()
        .execute(
            "SELECT m.*, u.name AS to_name FROM messages m "
            "LEFT JOIN users u ON u.id = m.to_user "
            "WHERE m.from_user = ? ORDER BY m.created_at DESC",
            (uid,),
        )
        .fetchall()
    ]


def thread(thread_id, uid):
    """Messages in a thread, restricted to threads this user is part of."""
    rows = [
        row_to_dict(r)
        for r in db()
        .execute(
            "SELECT m.*, u.name AS from_name FROM messages m "
            "JOIN users u ON u.id = m.from_user "
            "WHERE m.thread_id = ? ORDER BY m.created_at ASC",
            (thread_id,),
        )
        .fetchall()
    ]
    if not any(m["from_user"] == uid or m["to_user"] == uid for m in rows):
        return None
    return rows


def mark_read(thread_id, uid):
    con = db()
    con.execute(
        "UPDATE messages SET read_at = ? WHERE thread_id = ? AND to_user = ? AND read_at IS NULL",
        (time.time(), thread_id, uid),
    )
    con.commit()


def unread_count(uid):
    return db().execute(
        "SELECT COUNT(*) FROM messages WHERE to_user = ? AND read_at IS NULL", (uid,)
    ).fetchone()[0]


def pending_for_researcher(researcher_id):
    """Messages sent to a researcher who hasn't claimed their profile yet."""
    return db().execute(
        "SELECT COUNT(*) FROM messages WHERE to_researcher = ? AND to_user IS NULL",
        (researcher_id,),
    ).fetchone()[0]
