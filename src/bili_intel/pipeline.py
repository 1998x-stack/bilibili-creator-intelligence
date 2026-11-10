from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .asr import transcribe_audio
from .db import Database
from .llm import PROMPT_VERSION, analyze_transcript, to_markdown
from .subtitles import read_subtitle, sha256_text
from .ytdlp_adapter import download_audio, download_subtitles, extract_metadata, info_to_video_update


_LANG_PRIORITY = ("zh-cn", "zh-hans", "ai-zh", ".zh.", "zh-hant", "ai-en", ".en.")


def _choose_subtitle(paths: list[Path]) -> Path | None:
    subtitle_paths = [path for path in paths if path.suffix.lower() in {".srt", ".vtt"}]
    if not subtitle_paths:
        return None
    def score(path: Path) -> tuple[int, int, str]:
        name = path.name.lower()
        for index, marker in enumerate(_LANG_PRIORITY):
            if marker in name:
                return index, 0 if path.suffix.lower() == ".srt" else 1, name
        return len(_LANG_PRIORITY), 0 if path.suffix.lower() == ".srt" else 1, name
    return sorted(subtitle_paths, key=score)[0]


def _write_artifact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def process_video(
    db: Database,
    video: Any,
    settings,
    *,
    authorized_content_use: bool,
    fetch_metadata: bool = False,
    fetch_subtitles: bool = True,
    run_asr: bool = True,
    run_llm: bool = True,
) -> None:
    video_id = video["video_id"]
    url = video["url"]
    creator_mid = video["creator_mid"]
    work_dir = settings.artifacts_dir / video_id
    subtitle_dir = work_dir / "subtitles"
    audio_dir = work_dir / "audio"

    needs_remote_access = fetch_metadata or (
        db.latest_transcript(video_id) is None and (fetch_subtitles or run_asr)
    )
    if needs_remote_access and not authorized_content_use:
        raise PermissionError(
            "This stage accesses Bilibili pages/content. Re-run with --authorized-content-use "
            "only if you own the content or have the required permission."
        )

    if fetch_metadata:
        info = extract_metadata(url, settings)
        update = info_to_video_update(info, creator_mid, url, requested_video_id=video_id)
        db.upsert_video(update)
        video = db.get_videos(video_id=video_id)[0]

    if fetch_subtitles and db.latest_transcript(video_id) is None:
        db.log_job(video_id, "subtitle", "running")
        try:
            subtitle_files = download_subtitles(url, settings, subtitle_dir)
            selected = _choose_subtitle(subtitle_files)
            if selected:
                raw_subtitle, transcript_text = read_subtitle(selected)
                if transcript_text.strip():
                    digest = sha256_text(transcript_text)
                    db.add_transcript(
                        video_id, "bilibili_subtitle", selected.stem.split(".")[-1],
                        transcript_text, raw_subtitle, str(selected), digest,
                        subtitle_format=selected.suffix.lstrip("."),
                    )
                    db.log_job(video_id, "subtitle", "success", str(selected))
            else:
                db.log_job(video_id, "subtitle", "empty", "No SRT subtitle track found")
        except Exception as exc:
            # A subtitle failure should not block the configured ASR fallback.
            db.log_job(video_id, "subtitle", "failed", repr(exc))

    transcript = db.latest_transcript(video_id)
    if transcript is None and run_asr:
        db.log_job(video_id, "asr", "running")
        try:
            audio_path = download_audio(url, settings, audio_dir)
            raw_subtitle, language = transcribe_audio(audio_path, settings)
            srt_path = work_dir / "subtitles" / f"{video_id}.whisper.srt"
            _write_artifact(srt_path, raw_subtitle)
            _, transcript_text = read_subtitle(srt_path)
            if transcript_text.strip():
                digest = sha256_text(transcript_text)
                db.add_transcript(
                    video_id, "faster_whisper", language, transcript_text,
                    raw_subtitle, str(srt_path), digest,
                )
                db.log_job(video_id, "asr", "success", f"language={language}")
                transcript = db.latest_transcript(video_id)
        except Exception as exc:
            db.log_job(video_id, "asr", "failed", repr(exc))
            raise

    if run_llm:
        transcript = transcript or db.latest_transcript(video_id)
        if transcript is None:
            db.log_job(video_id, "llm", "skipped", "No transcript available")
            return
        if db.analysis_exists(video_id, transcript["content_sha256"], settings.llm_model, PROMPT_VERSION):
            db.log_job(video_id, "llm", "skipped", "Analysis already exists for this transcript/model/prompt")
            return
        db.log_job(video_id, "llm", "running")
        try:
            result = analyze_transcript(transcript["transcript_text"], settings)
            markdown = to_markdown(result)
            analysis_dir = work_dir / "analysis"
            _write_artifact(analysis_dir / "analysis.json", json.dumps(result, ensure_ascii=False, indent=2))
            _write_artifact(analysis_dir / "analysis.md", markdown)
            db.add_analysis(
                video_id, int(transcript["id"]), transcript["content_sha256"],
                "openai-compatible", settings.llm_model, PROMPT_VERSION, result, markdown,
            )
            db.log_job(video_id, "llm", "success", settings.llm_model)
        except Exception as exc:
            db.log_job(video_id, "llm", "failed", repr(exc))
            raise
