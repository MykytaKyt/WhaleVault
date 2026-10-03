"""Pydantic schemas for structured model output. The JSON schema sent to llama.cpp is derived from them."""
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TopicChoice(BaseModel):
    existing_topic_id: int | None = Field(None, description="id of an existing topic, or null to create a new one")
    new_topic_name: str | None = Field(None, description="name of the new topic (only if existing_topic_id is null)")
    new_topic_description: str | None = Field(None, description="one sentence: what belongs in the new topic")
    new_topic_emoji: str | None = Field(None, description="one emoji for the new topic")
    reason: str = Field(..., description="why this topic; for a new topic, why none of the existing ones fit")


class NoteMarkup(BaseModel):
    title: str = Field(..., max_length=120)
    summary: str = Field(..., max_length=500)
    topic: TopicChoice
    tags: list[str] = Field(..., min_length=1, max_length=5)
    is_question: bool = Field(..., description="true if the user is asking something rather than saving information")

    @field_validator("title", "summary")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


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
