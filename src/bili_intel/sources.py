"""Video discovery adapters. Network discovery requires an authorized operator."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol

from .manifest import load_manifest
from .security import sanitize_metadata
from .urltools import canonical_video_url, extract_mid, extract_video_id


class CreatorVideoSource(Protocol):
    def list_videos(self, creator_mid: str) -> list[dict[str, Any]]: ...


class ManifestSource:
    """Offline CSV import; statistics not present in the manifest remain NULL."""

    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path
        self.last_report: dict[str, Any] = {}

    def list_videos(self, creator_mid: str) -> list[dict[str, Any]]:
        videos = load_manifest(self.manifest_path, creator_mid)
        self.last_report = {"source": "manifest", "found": len(videos), "complete": None}
        return videos


def _entry_video_id(entry: dict[str, Any]) -> str | None:
    """Do not trust a playlist's `id` as a BVID without validating the shape."""
    for value in (entry.get('bvid'), entry.get('id'), entry.get('url'), entry.get('webpage_url')):
        if not value:
            continue
        value = str(value)
        if re.fullmatch(r'BV[0-9A-Za-z]{10}', value):
            return value
        if re.fullmatch(r'av\d+', value, re.IGNORECASE):
            return value
        try:
            return extract_video_id(value)
        except ValueError:
            continue
    return None


def normalize_playlist_entry(entry: dict[str, Any], creator_mid: str) -> dict[str, Any] | None:
    video_id = _entry_video_id(entry)
    if not video_id:
        return None
    uploader_mid = entry.get('uploader_id') or entry.get('channel_id')
    if uploader_mid and str(uploader_mid) != creator_mid:
        raise ValueError(f'Playlist entry {video_id} is attributed to another creator ({uploader_mid})')
    return {
        'video_id': video_id,
        'bvid': video_id if video_id.startswith('BV') else None,
        'aid': video_id[2:] if video_id.lower().startswith('av') else entry.get('aid'),
        'creator_mid': creator_mid,
        'url': canonical_video_url(video_id),
        'title': entry.get('title') or '',
        'description': entry.get('description') or '',
        'pubdate': entry.get('upload_date') or entry.get('release_date'),
        'duration_seconds': entry.get('duration'),
        'cover_url': entry.get('thumbnail'),
        'tags': entry.get('tags') or [],
        'stats': {key: entry.get(key) for key in (
            'view_count', 'like_count', 'coin_count', 'favorite_count',
            'share_count', 'danmaku_count', 'comment_count',
        )},
        'raw_metadata': sanitize_metadata(entry),
    }


class YtDlpSpaceSource:
    """Opt-in discovery using yt-dlp's BilibiliSpaceVideo extractor.

    This uses a non-official Bilibili endpoint under the hood. Access can be
    blocked/rate-limited, and discovery cannot establish the existence of
    unpublished, deleted or otherwise inaccessible videos.
    """

    def __init__(self, space_url: str, settings, *, max_videos: int = 0):
        self.space_url = space_url
        self.settings = settings
        if max_videos < 0:
            raise ValueError('max_videos must be >= 0')
        self.max_videos = max_videos
        self.last_report: dict[str, Any] = {}

    def list_videos(self, creator_mid: str) -> list[dict[str, Any]]:
        if extract_mid(self.space_url) != creator_mid:
            raise ValueError('Creator MID does not match the space URL')
        try:
            import yt_dlp
        except ImportError as exc:
            raise RuntimeError("Install yt-dlp: pip install -e .") from exc
        from .ytdlp_adapter import _ydl_options

        settings = self.settings
        options = {
            **_ydl_options(settings, settings.artifacts_dir / 'discovery'),
            'noplaylist': False,
            'extract_flat': 'in_playlist',
            'skip_download': True,
            'ignoreerrors': False,
            'playlistend': self.max_videos or None,
            'sleep_interval_requests': 1.0,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(f'https://space.bilibili.com/{creator_mid}/video', download=False)
            if not info or info.get('_type') != 'playlist':
                raise RuntimeError('Expected a creator playlist; Bilibili may be blocking the request')
            entries = info.get('entries')
            if entries is None:
                raise RuntimeError('Creator playlist has no entries field')
            videos: dict[str, dict[str, Any]] = {}
            unknown = 0
            for item in entries:
                if not item:
                    raise RuntimeError('Playlist yielded a missing entry; refusing to report an incomplete scan as complete')
                normalized = normalize_playlist_entry(item, creator_mid)
                if normalized is None:
                    unknown += 1
                else:
                    videos.setdefault(normalized['video_id'], normalized)
        if unknown:
            raise RuntimeError(f'{unknown} playlist entries were not video IDs; not claiming complete coverage')
        if not videos:
            raise RuntimeError('No videos discovered; check authorization, cookies and access restrictions')
        expected = info.get('playlist_count') or info.get('n_entries')
        self.last_report = {
            'source': 'yt-dlp:BilibiliSpaceVideo',
            'found': len(videos),
            'expected': expected,
            'complete': False if self.max_videos else None,
            'note': 'Best-effort accessible uploads; cannot prove every public upload was returned',
        }
        return list(videos.values())


class OfficialOpenPlatformSource:
    """Reserved for an app authorized to read a creator's official archive list.

    No credentials or guessed signatures are embedded in this package.
    """

    def list_videos(self, creator_mid: str) -> list[dict[str, Any]]:
        raise NotImplementedError('Configure an authorized Open Platform adapter for your approved app, or use an authorized manifest.')
