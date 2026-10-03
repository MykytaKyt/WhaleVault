import hashlib
import json
import math
import re
from pathlib import Path

import pytest

from bot.config import ROOT, Settings
from bot.db.connection import connect
from bot.deps import Deps
from bot.llm.client import LLMClient, LLMError
from bot.llm.schemas import NoteMarkup, TopicChoice

DIM = 64

# keyword stem -> topic name the fake model picks
TOPIC_RULES = [
    (("кіа", "киа", "kia", "соул", "каталіз", "катализ", "сто "), "Kia Soul", "🚗"),
    (("научрук", "статт", "стать", "диссерт", "дисер"), "Наука", "🎓"),
    (("врач", "лікар", "зуб", "анализ"), "Здоровье", "🩺"),
]


def fake_embedding(text: str) -> list[float]:
    """Bag of 5-letter word prefixes hashed into DIM buckets: same words -> similar vectors."""
    v = [0.0] * DIM
    for w in re.findall(r"\w+", text.lower()):
        h = int(hashlib.md5(w[:5].encode()).hexdigest(), 16)
        v[h % DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class FakeLLM(LLMClient):
    """Mock model with the same interface as LLMClient. No network."""

    def __init__(self):
        super().__init__("http://fake", routine="routine", answer="answer", embed="embed")
        self.calls: list[tuple[str, list[dict]]] = []
        self.fail_json = 0          # how many chat_json calls should fail
        self.answer_text = "Ответ по заметкам [#1]."
        self.question_markers = ("что я", "коли", "когда у меня")

    async def chat(self, model, messages, **params):
        self.calls.append((model, messages))
        text = messages[-1]["content"]
        text = re.sub(r"^\[.*?\]\n", "", text)
        return re.sub(r"\b(ну|короче|эээ)\b,?\s*", "", text).strip()

    async def chat_json(self, model, messages, schema, **params):
        self.calls.append((model, messages))
        if self.fail_json > 0:
            self.fail_json -= 1
            raise LLMError("invalid NoteMarkup")
        prompt = messages[-1]["content"]
        note = prompt.split("Note:\n", 1)[1].lower()
        topics = dict((name.strip().lower(), int(tid)) for tid, name in
                      re.findall(r"id=(\d+): \S* ?(.+?) —", prompt))
        target = None
        # Follow a past correction when the corrected note shares words with this one
        for line in prompt.split("Past corrections")[1].split("Note:\n")[0].splitlines():
            m = re.match(r'- "(.+)" → .+ → (.+)', line)
            if m and set(re.findall(r"\w{5,}", m.group(1).lower())) & set(re.findall(r"\w{5,}", note)):
                target = (m.group(2).strip(), "", "")
        if target is None:
            for keys, name, emoji in TOPIC_RULES:
                if any(k in note for k in keys):
                    target = (name, "desc", emoji)
                    break
        target = target or ("Разное", "misc", "🗂")
        tid = topics.get(target[0].lower())
        choice = TopicChoice(existing_topic_id=tid, new_topic_name=None if tid else target[0],
                             new_topic_description=None if tid else target[1],
                             new_topic_emoji=None if tid else target[2], reason="test")
        words = re.findall(r"\w+", note)
        return NoteMarkup(title=" ".join(words[:4]) or "заметка", summary=note[:100] or "-", topic=choice,
                          tags=[words[0] if words else "tag"],
                          is_question=note.strip().endswith("?") and any(q in note for q in self.question_markers))

    async def stream(self, model, messages, **params):
        self.calls.append((model, messages))
        for piece in re.findall(r".{1,5}", self.answer_text, re.S):
            yield piece

    async def embed(self, texts):
        return [fake_embedding(t) for t in texts]

    async def running(self):
        return []

    async def unload(self):
        return True


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, telegram_token="x", allowed_user_id=42, data_dir=tmp_path / "data",
                    logs_dir=tmp_path / "logs", backup_dir=tmp_path / "backups", embed_dim=DIM,
                    prompts_dir=ROOT / "bot" / "prompts", migrations_dir=ROOT / "migrations")


@pytest.fixture
def deps(settings) -> Deps:
    conn = connect(settings.db_path, settings.migrations_dir, settings.embed_dim)
    yield Deps(settings=settings, conn=conn, llm=FakeLLM())
    conn.close()
