"""Founder jargon -> plain English, for the researcher reading the message.

A professor who has never been near a startup gets an email saying the sender
is "pre-seed, pre-PMF, building a vertical SaaS play with a defensible moat and
looking for a technical advisor to de-risk the science." That is four sentences
of nothing, and it is a real reason cold outreach from founders gets ignored.

This rewrites the message into what it actually says, plus a glossary of the
terms used. It never invents commitments the sender didn't make -- the point is
to make the ask legible, not to make it sound better.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
MODEL = os.environ.get("RB_TRANSLATE_MODEL", "gpt-4.1-mini")

PROMPT = """You translate startup jargon into plain English for an academic reader who does not follow startup culture.

Given a message, return:
- "plain": the same message rewritten in plain, direct English. Same meaning, same commitments, same ask. Do not add enthusiasm, do not add claims, do not remove the specifics (papers, numbers, technical detail) — those are the useful parts. If a sentence is pure filler, drop it.
- "ask": one short sentence naming exactly what the sender wants from the reader.
- "glossary": array of {term, meaning} for genuine startup/business jargon that appeared. Plain technical or scientific terms are NOT jargon — do not explain "assay" or "thermostable" to a scientist. Empty array if the message had no jargon.
- "time_ask": the concrete time commitment being requested if one is stated (e.g. "15 minutes"), otherwise null.

Never invent facts. If the message is already plain, return it nearly unchanged and an empty glossary.

Return JSON with exactly those four keys."""


def translate(body, subject=None):
    from openai import OpenAI

    load_dotenv(ROOT / ".env")
    payload = {"subject": subject or "", "message": body[:6000]}
    resp = OpenAI().chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": json.dumps(payload)},
        ],
    )
    out = json.loads(resp.choices[0].message.content)
    return {
        "plain": out.get("plain") or "",
        "ask": out.get("ask") or "",
        "glossary": [
            g for g in (out.get("glossary") or []) if g.get("term") and g.get("meaning")
        ][:8],
        "time_ask": out.get("time_ask"),
    }
