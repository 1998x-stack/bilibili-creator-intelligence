"""Local-only environment checks. This module never makes network requests."""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _writable_location(path: Path, *, directory: bool) -> tuple[bool, str]:
    """Check the nearest existing parent without creating files or directories."""
    target = path if directory else path.parent
    if directory and target.exists() and not target.is_dir():
        return False, str(target)
    if not directory and path.exists() and path.is_dir():
        return False, str(path)
    probe = target
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return probe.is_dir() and os.access(probe, os.W_OK), str(probe)


def collect_diagnostics(settings: Any) -> list[dict[str, str]]:
    """Return local readiness checks; secret values are never included."""
    checks: list[dict[str, str]] = []

    def add(status: str, name: str, detail: str) -> None:
        checks.append({"status": status, "name": name, "detail": detail})

    if sys.version_info >= (3, 11):
        add("ok", "Python", sys.version.split()[0])
    else:
        add("fail", "Python", "Python 3.11 or newer is required")

    if _module_available("yt_dlp"):
        add("ok", "yt-dlp", "Installed")
    else:
        add("fail", "yt-dlp", "Missing; install the project with pip install -e '.[all,dev]'")

    if shutil.which("ffmpeg"):
        add("ok", "FFmpeg", "Available on PATH")
    else:
        add("warn", "FFmpeg", "Not found; audio extraction / ASR fallback will not work")

    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE temp.bci_fts_probe USING fts5(text, tokenize='trigram')")
            conn.execute("DROP TABLE temp.bci_fts_probe")
        finally:
            conn.close()
        add("ok", "SQLite FTS5 trigram", f"Available (SQLite {sqlite3.sqlite_version})")
    except sqlite3.Error as exc:
        add("fail", "SQLite FTS5 trigram", f"Unavailable: {type(exc).__name__}")

    if _module_available("faster_whisper"):
        add("ok", "faster-whisper", "Installed")
    else:
        add("warn", "faster-whisper", "Not installed; ASR fallback is unavailable")

    if _module_available("openai") and _module_available("tiktoken"):
        add("ok", "LLM dependencies", "OpenAI SDK and tiktoken are installed")
    else:
        add("warn", "LLM dependencies", "Install the optional LLM extra: pip install -e '.[llm]'")

    if os.getenv("OPENAI_API_KEY", "").strip():
        add("ok", "LLM API key", "Configured (value hidden)")
    else:
        add("warn", "LLM API key", "Not configured; LLM analysis will fail unless --no-llm is used")

    mode = getattr(settings, "llm_mode", "schema")
    if mode in {"schema", "json"}:
        add("ok", "LLM response mode", mode)
    else:
        add("fail", "LLM response mode", "BCI_LLM_MODE must be 'schema' or 'json'")

    budget = getattr(settings, "llm_budget_usd", None)
    input_price = getattr(settings, "llm_input_usd_per_mtok", None)
    output_price = getattr(settings, "llm_output_usd_per_mtok", None)
    if budget is not None and (input_price is None or output_price is None):
        add("fail", "LLM budget configuration", "A budget requires both input and output token prices")
    elif budget is not None:
        add("ok", "LLM budget configuration", "Budget and both token prices are configured")
    else:
        add("info", "LLM budget configuration", "Estimated spend cap is disabled")

    cookies_file = getattr(settings, "cookies_file", None)
    if cookies_file is None:
        add("info", "Bilibili cookies", "No cookie file configured")
    elif Path(cookies_file).is_file():
        add("ok", "Bilibili cookies", "Configured file exists (contents hidden)")
    else:
        add("warn", "Bilibili cookies", "Configured file does not exist")

    db_ok, db_probe = _writable_location(Path(settings.db_path), directory=False)
    add("ok" if db_ok else "fail", "Database location",
        f"Writable parent: {db_probe}" if db_ok else f"Parent is not writable: {db_probe}")

    artifacts_ok, artifacts_probe = _writable_location(Path(settings.artifacts_dir), directory=True)
    add("ok" if artifacts_ok else "fail", "Artifacts location",
        f"Writable directory or parent: {artifacts_probe}" if artifacts_ok
        else f"Directory path is not writable: {artifacts_probe}")

    return checks
