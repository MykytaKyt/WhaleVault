import hashlib
import json
import math
import re
from datetime import date, timedelta
from pathlib import Path

import pytest

from bot.config import ROOT, Settings
from bot.db.connection import connect
from bot.deps import Deps
from bot.llm.client import LLMClient, LLMError
from bot.llm.schemas import (EditIntent, EntityRef, Extraction, FactItem, NoteMarkup, TaskItem,
                             TopicChoice)

DIM = 64

# keyword stem -> entity the fake model extracts
ENTITY_RULES = [
    (("кіа", "киа", "kia", "соул"), "Kia Soul", "car"),
    (("сергей", "сергі", "сергію"), "Сергей", "person"),
    (("научрук",), "Научрук", "person"),
]
TASK_MARKERS = ("спросить", "купить", "записаться", "записатися", "треба", "надо", "позвонить")

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
        self.fail_chat = False      # simulate the llm container being down
        self.answer_text = "Ответ по заметкам [#1]."
        self.question_markers = ("что я", "коли", "когда у меня")

    async def chat(self, model, messages, **params):
        self.calls.append((model, messages))
        if self.fail_chat:
            raise LLMError("ConnectError: llm is down")
        if "summary page of one topic" in messages[0]["content"]:
            ids = re.findall(r"\[#(\d+)\]", messages[-1]["content"])
            cite = " ".join(f"[#{i}]" for i in ids[:2])
            return ("Вот сводка:\n## Что известно\nКатализатор забит, ремонт оценили в 12 000 грн " + cite +
                    ".\n\n## Открытые вопросы и задачи\n- Спросить контакты мастера\n\n"
                    "## Что изменилось за неделю\nНовая оценка ремонта " + cite + ".")
        text = messages[-1]["content"]
        text = re.sub(r"^\[.*?\]\n", "", text)
        return re.sub(r"\b(ну|короче|эээ)\b,?\s*", "", text).strip()

    @staticmethod
    def _today(prompt: str) -> date:
        return date.fromisoformat(re.search(r"Today: (\d{4}-\d{2}-\d{2})", prompt).group(1))

    def _extract(self, prompt: str, original: str) -> Extraction:
        text = original.lower()
        today = self._today(prompt)
        ents = [EntityRef(name=name, kind=kind) for keys, name, kind in ENTITY_RULES if any(k in text for k in keys)]
        facts, tasks = [], []
        is_task = any(m in text for m in TASK_MARKERS)
        for e in ents:
            if is_task:
                break
            replaces = None
            if "теперь" in text:  # an update: replace the newest known fact about this entity
                m = re.findall(rf"fact_id=(\d+) \[{re.escape(e.name)}\]", prompt)
                replaces = int(m[0]) if m else None
            facts.append(FactItem(entity=e.name, text=original.strip()[:200], replaces_fact_id=replaces))
        if is_task:
            due = None
            if "пятниц" in text:
                due = (today + timedelta(days=(4 - today.weekday()) % 7 or 7)).isoformat()
            elif "завтра" in text:
                due = (today + timedelta(days=1)).isoformat()
            tasks.append(TaskItem(text=original.strip()[:150], due=due))
        return Extraction(entities=ents, facts=facts, tasks=tasks)

    def _edit(self, prompt: str) -> EditIntent:
        original = prompt.split("The reply:\n", 1)[1].strip()
        reply = original.lower()
        topics = re.findall(r"id=(\d+): \S* ?(.+?) —", prompt)
        if m := re.match(r"перенеси в (.+)", reply):
            want = m.group(1)[:3]
            hit = [int(i) for i, name in topics if name.lower().startswith(want)]
            return EditIntent(intent="move_topic", topic_id=hit[0] if hit else None,
                              new_topic_name=None if hit else m.group(1).title())
        if m := re.match(r"назови (.+)", reply):
            return EditIntent(intent="rename", title=original[len("назови "):].strip("«»\" "))
        if m := re.match(r"объедини с заметкой про (.+)", reply):
            return EditIntent(intent="merge_with", merge_query=m.group(1))
        if m := re.match(r"тег (.+)", reply):
            return EditIntent(intent="add_tag", tag=m.group(1))
        if reply.startswith("удали"):
            return EditIntent(intent="delete")
        if "на пятницу" in reply:
            today = self._today(prompt)
            return EditIntent(intent="set_task_date",
                              date=(today + timedelta(days=(4 - today.weekday()) % 7 or 7)).isoformat())
        return EditIntent(intent="none")

    async def chat_json(self, model, messages, schema, **params):
        self.calls.append((model, messages))
        if self.fail_json > 0:
            self.fail_json -= 1
            raise LLMError("invalid NoteMarkup")
        prompt = messages[-1]["content"]
        if schema.__name__ == "SplitProposal":
            ids = [int(i) for i in re.findall(r"\[#(\d+)\]", prompt)]
            half = len(ids) // 2 or 1
            return schema(groups=[{"name": "Ремонт", "emoji": "🔧", "note_ids": ids[:half]},
                                  {"name": "Обслуживание", "emoji": "🛢", "note_ids": ids[half:]}], reason="test")
        if schema is EditIntent:
            return self._edit(prompt)
        if schema is Extraction:
            return self._extract(prompt, prompt.split("Clarification:\n", 1)[1])
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
        x = self._extract(prompt, prompt.split("Note:\n", 1)[1])
        return NoteMarkup(title=" ".join(words[:4]) or "заметка", summary=note[:100] or "-", topic=choice,
                          tags=[words[0] if words else "tag"], entities=x.entities, facts=x.facts, tasks=x.tasks,
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
