from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .urltools import canonical_video_url, extract_video_id


_STAT_FIELDS = (
    "view_count", "like_count", "coin_count", "favorite_count",
    "share_count", "danmaku_count", "comment_count",
)


def _int_or_none(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"Expected integer or empty value, got {value!r}") from exc


def _float_or_none(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value.strip())
    except ValueError as exc:
        raise ValueError(f"Expected number or empty value, got {value!r}") from exc


def load_manifest(path: Path, creator_mid: str) -> list[dict[str, Any]]:
    """Load a CSV manifest. Empty metric cells remain None, never coerced to zero."""
    videos: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "video_url" not in reader.fieldnames:
            raise ValueError("Manifest must contain a 'video_url' column")
        for line_number, row in enumerate(reader, start=2):
            url = (row.get("video_url") or "").strip()
            if not url:
                continue
            video_id = (row.get("bvid") or "").strip() or extract_video_id(url)
            # Canonicalize every URL: do not persist arbitrary unvalidated inputs.
            url = canonical_video_url(video_id)
            tags_raw = (row.get("tags") or "").strip()
            if tags_raw.startswith("["):
                tags = json.loads(tags_raw)
            else:
                tags = [item.strip() for item in tags_raw.split("|") if item.strip()]
            raw_meta_raw = (row.get("raw_metadata_json") or "{}").strip() or "{}"
            try:
                raw_metadata = json.loads(raw_meta_raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid raw_metadata_json on CSV line {line_number}") from exc
            stats = {field: _int_or_none(row.get(field)) for field in _STAT_FIELDS}
            # Also normalize Bilibili-style raw stat keys when the CSV columns are empty.
            raw_stat = raw_metadata.get("stat", {}) if isinstance(raw_metadata, dict) else {}
            if not isinstance(raw_stat, dict) or not raw_stat:
                data = raw_metadata.get("data", {}) if isinstance(raw_metadata, dict) else {}
                view = data.get("View", {}) if isinstance(data, dict) else {}
                raw_stat = view.get("stat", {}) if isinstance(view, dict) else {}
            if not isinstance(raw_stat, dict):
                raw_stat = {}
            raw_key_map = {
                "view_count": "view", "like_count": "like", "coin_count": "coin",
                "favorite_count": "favorite", "share_count": "share",
                "danmaku_count": "danmaku", "comment_count": "reply",
            }
            for field, raw_key in raw_key_map.items():
                if stats[field] is None and raw_stat.get(raw_key) is not None:
                    stats[field] = int(raw_stat[raw_key])
            video = {
                "video_id": video_id,
                "bvid": video_id if video_id.startswith("BV") else None,
                "aid": video_id[2:] if video_id.startswith("av") else None,
                "creator_mid": creator_mid,
                "title": (row.get("title") or "").strip(),
                "description": (row.get("description") or "").strip(),
                "url": url,
                "pubdate": (row.get("pubdate") or "").strip() or None,
                "duration_seconds": _float_or_none(row.get("duration")),
                "category": (row.get("category") or "").strip() or None,
                "cover_url": (row.get("cover_url") or "").strip() or None,
                "tags": tags,
                "stats": stats,
                "raw_metadata": raw_metadata,
                "raw_stats": raw_stat if isinstance(raw_stat, dict) else {},
            }
            videos.append(video)
    return videos
