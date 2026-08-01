"""Resume upload -> plain text.

The text feeds two things: it gives the intro-email drafter real detail about
the founder ("junior in CBE who built a spectrometer for a class project" beats
"a Princeton undergraduate"), and it can seed a match query when someone has no
problem statement written yet.

PDF and plain text only. No .doc parsing -- it is a swamp and nobody needs it
before Sunday.
"""

import io

MAX_BYTES = 5 * 1024 * 1024
MAX_CHARS = 20_000


class ResumeError(ValueError):
    pass


def extract(filename, raw):
    if len(raw) > MAX_BYTES:
        raise ResumeError("Resume must be under 5 MB.")

    name = (filename or "").lower()
    if name.endswith(".pdf") or raw[:5] == b"%PDF-":
        text = _from_pdf(raw)
    elif name.endswith((".txt", ".md")):
        text = raw.decode("utf-8", errors="replace")
    else:
        raise ResumeError("Upload a PDF, .txt, or .md file.")

    text = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    if len(text) < 80:
        raise ResumeError(
            "Couldn't read any text out of that file. If it's a scanned PDF, "
            "paste the text instead."
        )
    return text[:MAX_CHARS]


def _from_pdf(raw):
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ResumeError("That PDF is password-protected.")
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except ResumeError:
        raise
    except Exception as e:
        raise ResumeError(f"Couldn't parse that PDF: {e}")
