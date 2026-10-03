"""Pydantic schemas for structured model output. The JSON schema sent to llama.cpp is derived from them."""
import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

EntityKind = Literal["person", "car", "project", "place", "other"]
_DUE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")


def check_due(v: str | None) -> str | None:
    """Accept YYYY-MM-DD or YYYY-MM-DDTHH:MM that is a real date; anything else becomes null."""
    if not v or not _DUE.match(v.strip()):
        return None
    v = v.strip()
    try:
        (datetime.fromisoformat(v) if "T" in v else date.fromisoformat(v))
    except ValueError:
        return None
    return v


class TopicChoice(BaseModel):
    existing_topic_id: int | None = Field(None, description="id of an existing topic, or null to create a new one")
    new_topic_name: str | None = Field(None, description="name of the new topic (only if existing_topic_id is null)")
    new_topic_description: str | None = Field(None, description="one sentence: what belongs in the new topic")
    new_topic_emoji: str | None = Field(None, description="one emoji for the new topic")
    reason: str = Field(..., description="why this topic; for a new topic, why none of the existing ones fit")


class EntityRef(BaseModel):
    name: str = Field(..., description="canonical name; reuse the exact name of a known entity")
    kind: EntityKind
    aliases: list[str] = Field(default_factory=list, max_length=5,
                               description="other ways the note refers to it")


class FactItem(BaseModel):
    entity: str = Field(..., description="name of the entity this fact is about (from entities)")
    text: str = Field(..., max_length=300, description="one atomic statement, self-contained")
    replaces_fact_id: int | None = Field(None, description="id of a known fact this one contradicts or updates")


class TaskItem(BaseModel):
    text: str = Field(..., max_length=200)
    due: str | None = Field(None, description="YYYY-MM-DD or YYYY-MM-DDTHH:MM, or null if no date")

    _due = field_validator("due")(classmethod(lambda cls, v: check_due(v)))


class NoteMarkup(BaseModel):
    title: str = Field(..., max_length=120)
    summary: str = Field(..., max_length=500)
    topic: TopicChoice
    tags: list[str] = Field(..., min_length=1, max_length=5)
    entities: list[EntityRef] = Field(default_factory=list, max_length=8)
    facts: list[FactItem] = Field(default_factory=list, max_length=12)
    tasks: list[TaskItem] = Field(default_factory=list, max_length=5)
    is_question: bool = Field(..., description="true if the user is asking something rather than saving information")

    @field_validator("title", "summary")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class Extraction(BaseModel):
    """Entities, facts and tasks only — for a clarification appended to an existing note."""
    entities: list[EntityRef] = Field(default_factory=list, max_length=8)
    facts: list[FactItem] = Field(default_factory=list, max_length=12)
    tasks: list[TaskItem] = Field(default_factory=list, max_length=5)


EditAction = Literal["move_topic", "rename", "merge_with", "add_tag", "delete", "set_task_date", "none"]


class EditIntent(BaseModel):
    """What a reply to a bot message about a note asks to do with that note."""
    intent: EditAction
    topic_id: int | None = Field(None, description="move_topic: id of an existing topic")
    new_topic_name: str | None = Field(None, description="move_topic: name of a new topic if none fits")
    title: str | None = Field(None, description="rename: the new title")
    merge_query: str | None = Field(None, description="merge_with: words describing the other note")
    tag: str | None = Field(None, description="add_tag: the tag")
    date: str | None = Field(None, description="set_task_date: YYYY-MM-DD or YYYY-MM-DDTHH:MM")

    _date = field_validator("date")(classmethod(lambda cls, v: check_due(v)))


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic schema with $refs inlined and titles dropped — simpler for llama.cpp's grammar converter."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)
