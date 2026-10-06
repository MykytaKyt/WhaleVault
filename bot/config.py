"""All settings come from the environment (.env). Nothing model- or path-specific is hard-coded."""
from datetime import time
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", env_ignore_empty=True)

    tz: str = Field("Europe/Kyiv", alias="TZ")

    telegram_token: str = ""
    allowed_user_id: int = 0

    # Paths
    data_dir: Path = ROOT / "data"
    logs_dir: Path = ROOT / "logs"
    backup_dir: Path = ROOT / "backups"
    prompts_dir: Path = ROOT / "bot" / "prompts"
    migrations_dir: Path = ROOT / "migrations"

    # Model API (llama-swap or any OpenAI-compatible server, e.g. Ollama at http://host:11434)
    llm_url: str = "http://llm:8080"
    llm_timeout: float = 600.0
    routine_model_name: str = "routine"
    answer_model_name: str = "answer"
    embed_model_name: str = "embed"
    embed_dim: int = 1024
    ask_thinking: bool = False
    # Set to 0 for servers without llama.cpp grammar support; JSON is still validated by pydantic
    llm_json_schema: bool = True

    # Idle unload: llama-swap handles the daytime ttl; at night the bot unloads sooner
    llm_ttl_night: int = 60
    llm_day_start: time = time(8, 0)
    llm_day_end: time = time(23, 0)

    # Pipeline
    link_max_chars: int = 6000
    chunk_chars: int = 500
    duplicate_threshold: float = 0.92
    similar_notes: int = 3
    feedback_examples: int = 5

    # Ask
    ask_top_notes: int = 8
    ask_candidates: int = 20
    ask_context_tokens: int = 10000
    ask_edit_interval: float = 1.5

    # Jobs
    gpu_log_minutes: int = 5
    gpu_temp_alert: int = 85
    backup_cron: str = "30 4 * * *"
    remind_cron: str = "0 9 * * *"
    backup_keep: int = 14
    purge_deleted_days: int = 30

    # Energy for the dashboard: price per kWh, night tariff hours (same currency for both)
    energy_price_day: float = 0.0
    energy_price_night: float = 0.0
    energy_night_start: time = time(23, 0)
    energy_night_end: time = time(7, 0)
    energy_currency: str = "грн"

    # Web UI (stage 4)
    web_password: str = ""
    web_session_days: int = 30

    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "notes.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
