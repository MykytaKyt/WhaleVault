"""Prompts live in bot/prompts/*.md and are re-read on every call, so they can be edited live.

File format: system prompt, then a line `=== USER ===`, then the user message template.
Placeholders are {{name}}; missing values raise KeyError so typos are caught.
"""
import re
from pathlib import Path

SEPARATOR = "=== USER ==="
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render(prompts_dir: Path, prompt: str, /, **values: object) -> list[dict[str, str]]:
    text = (prompts_dir / f"{prompt}.md").read_text(encoding="utf-8")
    system, _, user = text.partition(SEPARATOR)

    def fill(s: str) -> str:
        return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), s).strip()

    messages = [{"role": "system", "content": fill(system)}]
    if user.strip():
        messages.append({"role": "user", "content": fill(user)})
    return messages
