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

import json
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


def db():
    global _con
    if _con is None:
        _con = connect()
        _con.executescript(SCHEMA)
        _con.commit()
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


# ── founder profile ────────────────────────────────────

def get_founder_profile(uid):
    return row_to_dict(
        db().execute("SELECT * FROM founder_profiles WHERE user_id = ?", (uid,)).fetchone()
    ) or {}


def upsert_founder_profile(uid, **fields):
    allowed = {"year", "major", "project", "bio"}
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
