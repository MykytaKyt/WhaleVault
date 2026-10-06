"""Shared runtime objects passed to the pipeline, handlers and jobs."""
import asyncio
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .config import Settings
from .llm.client import LLMClient


@dataclass
class Deps:
    settings: Settings
    conn: sqlite3.Connection
    llm: LLMClient
    # One GPU user at a time: the note worker, /ask and the web API never run LLM calls in parallel.
    # In production this is a GpuLock (cross-process); tests use a plain asyncio.Lock.
    gpu_lock: Any = field(default_factory=asyncio.Lock)
