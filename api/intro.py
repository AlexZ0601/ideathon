"""Draft a warm-intro email from a founder to a matched researcher.

The email's credibility comes from specificity: it cites the researcher's
actual paper and names the technical connection. Generic cold email is the
thing this product exists to replace, so the prompt forbids it explicitly.

We never invent a recipient address. OpenAlex has no contact data, and a
guessed netid is worse than a blank — the caller looks it up on the
department page.

Usage:
    python api/intro.py --researcher-id https://openalex.org/A5042307561 \
        --work-id https://openalex.org/W123 \
        --problem "our enzyme assay degrades above 40C" \
        --founder-name "Alex Zeng" --founder-year junior --founder-major CBE \
        --project "a field-deployable diagnostic for water-borne pathogens"
"""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
INTRO_MODEL = os.environ.get("RB_INTRO_MODEL", "gpt-4.1")

SYSTEM_PROMPT = """You draft short outreach emails from Princeton undergraduates to researchers whose published work is relevant to a technical problem the student is working on.

Rules:
- Under 150 words. Professors skim.
- Reference the specific paper by name and say what in it connects to the student's problem. Use a real detail from the abstract — this is the whole point.
- Ask for one concrete, small thing: 15 minutes, or a pointer to the right person.
- Plain, direct student voice. No flattery ("groundbreaking", "I was fascinated"), no filler, no MBA tone.
- Never invent facts about the student or the researcher beyond what you are given.
- If a resume excerpt is provided, you may cite one concrete thing from it (a course, project, or skill) when it is genuinely relevant to the researcher's work. Never inflate it, and never claim experience the resume does not state.
- If the paper is only loosely related, be honest about the connection rather than overstating it.
- Address the recipient by last name with the right title: "Prof. X" if they are an established PI, "Dr. X" or first name if they are early-career.

Return JSON: {"subject": "...", "body": "..."}
The body must contain real newlines between paragraphs and end with a sign-off using the student's name."""


def load_researchers():
    with open(DATA_DIR / "researchers.json") as f:
        return json.load(f)


def find(researchers, researcher_id, work_id=None):
    researcher = next((r for r in researchers if r["id"] == researcher_id), None)
    if researcher is None:
        raise SystemExit(f"no researcher with id {researcher_id}")
    works = researcher["works"]
    work = next((w for w in works if w["id"] == work_id), None) if work_id else None
    return researcher, work or works[0]


def draft(researcher, work, problem, founder, model=INTRO_MODEL):
    from openai import OpenAI

    load_dotenv(ROOT / ".env")
    is_pi = (researcher.get("seniority") or 0) >= 0.5
    student = {k: v for k, v in founder.items() if k != "resume_text"}
    if founder.get("resume_text"):
        # real background beats "a Princeton undergraduate", but the model must
        # quote it rather than embellish it
        student["resume_excerpt"] = founder["resume_text"][:2500]
    payload = {
        "student": student,
        "problem": problem,
        "researcher": {
            "name": researcher["name"],
            "field": researcher["dept"],
            "seniority": "established PI" if is_pi else "early-career researcher",
        },
        "paper": {
            "title": work["title"],
            "year": work["year"],
            "abstract": (work.get("abstract") or "")[:1500],
        },
    }
    resp = OpenAI().chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload)},
        ],
    )
    email = json.loads(resp.choices[0].message.content)
    email["to_hint"] = (
        f"Look up {researcher['name']}'s address on their Princeton department page — "
        "we don't guess contact details."
    )
    return email


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--researcher-id", required=True)
    p.add_argument("--work-id")
    p.add_argument("--problem", required=True)
    p.add_argument("--founder-name", default="a Princeton undergraduate")
    p.add_argument("--founder-year", default="junior")
    p.add_argument("--founder-major", default=None)
    p.add_argument("--project", default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    researcher, work = find(load_researchers(), args.researcher_id, args.work_id)
    email = draft(
        researcher,
        work,
        args.problem,
        {
            "name": args.founder_name,
            "year": args.founder_year,
            "major": args.founder_major,
            "project": args.project,
        },
    )

    if args.json:
        print(json.dumps(email, indent=2))
        return
    print(f"To:      {researcher['name']}  ({email['to_hint']})")
    print(f"Subject: {email['subject']}\n")
    print(email["body"])


if __name__ == "__main__":
    main()
