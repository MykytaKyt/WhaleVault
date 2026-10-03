"""Step 2: turn the raw input into text for the model (no LLM). Voice/link/photo arrive in stage 5."""
import sqlite3


def prepare(note: sqlite3.Row) -> tuple[str, str]:
    """Return (text, context) for the model."""
    context = note["context"] or ""
    return note["raw_text"].strip(), context
