"""Shared runtime objects passed to the pipeline, handlers and jobs."""
import asyncio
import sqlite3
from dataclasses import dataclass, field

from .config import Settings
from .llm.client import LLMClient


@dataclass
class Deps:
    settings: Settings
    conn: sqlite3.Connection
    llm: LLMClient
    # One GPU user at a time: the note worker and /ask never run LLM calls in parallel
    gpu_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
