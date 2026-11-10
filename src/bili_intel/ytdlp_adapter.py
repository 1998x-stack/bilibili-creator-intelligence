from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SUBTITLE_LANGS = ["zh-Hans", "zh-CN", "zh", "ai-zh", "zh-Hant", "en", "ai-en"]


def _ydl_options(settings, out_dir: Path, cookies: bool = True) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "http_headers": {"Referer": "https://www.bilibili.com/"},
    }
    if cookies and settings.cookies_file and settings.cookies_file.exists():
        options["cookiefile"] = str(settings.cookies_file)
    return options


def extract_metadata(url: str, settings) -> dict[str, Any]:
    """Extract fields yt-dlp exposes. Missing counters remain None."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp is required. Install with: pip install -e .") from exc
    with yt_dlp.YoutubeDL({**_ydl_options(settings, settings.artifacts_dir / "metadata"), "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise RuntimeError(f"yt-dlp returned no metadata for {url}")
    return info


def list_subtitle_tracks(url: str, settings) -> list[dict[str, Any]]:
    """Inspect subtitle tracks before downloading; includes manual and automatic tracks."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp is required. Install with: pip install -e .") from exc
    options = {**_ydl_options(settings, settings.artifacts_dir / "subtitle-probe"), "skip_download": True}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        return []
    tracks: list[dict[str, Any]] = []
    for group_name in ("subtitles", "automatic_captions"):
        group = info.get(group_name) or {}
        for language, formats in group.items():
            for item in formats or []:
                tracks.append({
                    "language": language,
                    "ext": item.get("ext"),
                    "name": item.get("name"),
                    "source_group": group_name,
                })
    return tracks


def download_subtitles(url: str, settings, output_dir: Path) -> list[Path]:
    """Inspect then download available subtitle tracks only; no full video is downloaded."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp is required. Install with: pip install -e .") from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    tracks = list_subtitle_tracks(url, settings)
    if not tracks:
        return []
    available = {
        track["language"] for track in tracks
        if track["language"].lower() not in {"danmaku", "live_chat", "live-chat"}
    }
    selected_langs = [lang for lang in SUBTITLE_LANGS if lang in available]
    # Keep any other available tracks as a final fallback for multilingual videos.
    selected_langs.extend(lang for lang in sorted(available) if lang not in selected_langs)
    if not selected_langs:
        return []
    options = {
        **_ydl_options(settings, output_dir),
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": selected_langs,
        "subtitlesformat": "srt/best",
        "overwrites": False,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([url])
    return sorted(output_dir.glob("*.srt")) + sorted(output_dir.glob("*.vtt"))


def download_audio(url: str, settings, output_dir: Path) -> Path:
    """Download/extract audio. Caller must have confirmed rights/authorization."""
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp is required. Install with: pip install -e .") from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    options = {
        **_ydl_options(settings, output_dir),
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "overwrites": False,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info.get("id") if info else None
    if not video_id:
        raise RuntimeError(f"Could not determine downloaded audio filename for {url}")
    audio_path = output_dir / f"{video_id}.mp3"
    if not audio_path.exists():
        candidates = list(output_dir.glob(f"{video_id}.*"))
        candidates = [p for p in candidates if p.suffix.lower() in {".m4a", ".webm", ".opus", ".mp3"}]
        if not candidates:
            raise FileNotFoundError(f"Audio file not found for {video_id}")
        return candidates[0]
    return audio_path


def info_to_video_update(
    info: dict[str, Any], creator_mid: str, fallback_url: str,
    requested_video_id: str | None = None,
) -> dict[str, Any]:
    extracted_id = str(info.get("id") or "")
    video_id = requested_video_id or extracted_id
    stats = {
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "coin_count": info.get("coin_count"),
        "favorite_count": info.get("favorite_count"),
        "share_count": info.get("share_count"),
        "danmaku_count": info.get("danmaku_count"),
    }
    # Never persist stream URLs / cookies / HTTP headers that could embed access tokens.
    SAFE_META_KEYS = (
        'id', 'display_id', 'title', 'description', 'webpage_url', 'duration',
        'upload_date', 'release_date', 'timestamp', 'uploader', 'uploader_id',
        'channel', 'channel_id', 'categories', 'tags', 'view_count', 'like_count',
        'coin_count', 'favorite_count', 'share_count', 'danmaku_count',
        'comment_count', 'thumbnail', 'aid',
    )
    raw = {key: info[key] for key in SAFE_META_KEYS if key in info}
    return {
        "video_id": video_id,
        "bvid": extracted_id if extracted_id.startswith("BV") else (info.get("display_id") if str(info.get("display_id", "")).startswith("BV") else None),
        "aid": (str(info.get("id"))[2:] if str(info.get("id", "")).startswith("av") else info.get("aid")),
        "creator_mid": creator_mid,
        "title": info.get("title") or "",
        "description": info.get("description") or "",
        "url": info.get("webpage_url") or fallback_url,
        "pubdate": info.get("upload_date") or info.get("release_date"),
        "duration_seconds": info.get("duration"),
        "category": info.get("categories", [None])[0] if info.get("categories") else None,
        "cover_url": info.get("thumbnail"),
        "tags": info.get("tags") or [],
        "stats": stats,
        "raw_metadata": raw,
        "raw_stats": stats,
    }
