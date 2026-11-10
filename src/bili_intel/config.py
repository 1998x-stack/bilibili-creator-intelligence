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
    llm_max_input_tokens: int
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    whisper_language: str | None
    workers: int
    network_workers: int
    asr_workers: int
    llm_workers: int
    llm_rpm: int
    llm_tpm: int
    llm_max_output_tokens: int
    llm_input_usd_per_mtok: float | None
    llm_output_usd_per_mtok: float | None
    llm_budget_usd: float | None
    llm_mode: str
    cookies_file: Path | None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        cookies = os.getenv("BCI_COOKIES_FILE", "").strip()
        settings = cls(
            db_path=Path(os.getenv("BCI_DB_PATH", "./data/bilibili.sqlite3")).expanduser(),
            artifacts_dir=Path(os.getenv("BCI_ARTIFACTS_DIR", "./data/artifacts")).expanduser(),
            llm_model=os.getenv("BCI_LLM_MODEL", "gpt-4o-mini"),
            llm_max_chars=max(3000, int(os.getenv("BCI_LLM_MAX_CHARS", "12000"))),
            llm_max_input_tokens=max(1024, int(os.getenv('BCI_LLM_MAX_INPUT_TOKENS', '6000'))),
            whisper_model=os.getenv("BCI_WHISPER_MODEL", "small"),
            whisper_device=os.getenv("BCI_WHISPER_DEVICE", "auto"),
            whisper_compute_type=os.getenv("BCI_WHISPER_COMPUTE_TYPE", "int8"),
            whisper_language=os.getenv('BCI_WHISPER_LANGUAGE') or None,
            workers=max(1, int(os.getenv('BCI_WORKERS', '2'))),
            network_workers=max(1, int(os.getenv('BCI_NETWORK_WORKERS', '1'))),
            asr_workers=max(1, int(os.getenv('BCI_ASR_WORKERS', '1'))),
            llm_workers=max(1, int(os.getenv('BCI_LLM_WORKERS', '2'))),
            llm_rpm=max(1, int(os.getenv('BCI_LLM_RPM', '30'))),
            llm_tpm=max(1, int(os.getenv('BCI_LLM_TPM', '60000'))),
            llm_max_output_tokens=max(256, int(os.getenv('BCI_LLM_MAX_OUTPUT_TOKENS', '1500'))),
            llm_input_usd_per_mtok=(float(os.environ['BCI_LLM_INPUT_USD_PER_MTOK'])
                                    if os.getenv('BCI_LLM_INPUT_USD_PER_MTOK') else None),
            llm_output_usd_per_mtok=(float(os.environ['BCI_LLM_OUTPUT_USD_PER_MTOK'])
                                     if os.getenv('BCI_LLM_OUTPUT_USD_PER_MTOK') else None),
            llm_budget_usd=(float(os.environ['BCI_LLM_BUDGET_USD'])
                            if os.getenv('BCI_LLM_BUDGET_USD') else None),
            llm_mode=os.getenv('BCI_LLM_MODE', 'schema'),
            cookies_file=Path(cookies).expanduser() if cookies else None,
        )
        if any(value is not None and value < 0 for value in (
            settings.llm_input_usd_per_mtok,settings.llm_output_usd_per_mtok,settings.llm_budget_usd
        )):
            raise ValueError('Token pricing and LLM budget must be non-negative')
        return settings
