from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    db_path: Path
    artifacts_dir: Path
    llm_model: str
    llm_max_chars: int
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    cookies_file: Path | None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        cookies = os.getenv("BCI_COOKIES_FILE", "").strip()
        return cls(
            db_path=Path(os.getenv("BCI_DB_PATH", "./data/bilibili.sqlite3")).expanduser(),
            artifacts_dir=Path(os.getenv("BCI_ARTIFACTS_DIR", "./data/artifacts")).expanduser(),
            llm_model=os.getenv("BCI_LLM_MODEL", "gpt-4o-mini"),
            llm_max_chars=max(3000, int(os.getenv("BCI_LLM_MAX_CHARS", "12000"))),
            whisper_model=os.getenv("BCI_WHISPER_MODEL", "small"),
            whisper_device=os.getenv("BCI_WHISPER_DEVICE", "auto"),
            whisper_compute_type=os.getenv("BCI_WHISPER_COMPUTE_TYPE", "int8"),
            cookies_file=Path(cookies).expanduser() if cookies else None,
        )
