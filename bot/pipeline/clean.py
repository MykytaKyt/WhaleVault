"""Step 3: clean_text from raw text (routine model)."""
from ..deps import Deps
from ..llm.prompts import render


async def clean(deps: Deps, text: str, context: str = "", source: str = "text") -> str:
    s = deps.settings
    prompt = "clean_link" if source == "link" else "clean"
    ctx = f"[{context}]\n" if context else ""
    messages = render(s.prompts_dir, prompt, text=text, context=ctx)
    out = await deps.llm.chat(deps.llm.routine, messages, temperature=0.2,
                              max_tokens=max(256, min(4096, len(text) // 2 + 200)))
    # Guard against a model that answers instead of cleaning, or returns nothing
    if source != "link" and (not out or len(out) > len(text) * 1.5 + 80):
        return text
    return out or text
