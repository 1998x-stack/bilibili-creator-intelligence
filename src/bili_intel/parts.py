"""Inventory all p=N parts of one Bilibili submission using yt-dlp's playlist mode.

An anthology is *not* a single video. Refuse ambiguous partial results, rather
than claim a complete transcript when some parts are missing.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode


def part_url(video_id: str, index: int) -> str:
    if not re.fullmatch(r'BV[0-9A-Za-z]{10}|av\d+', video_id, re.I) or index < 1:
        raise ValueError('Invalid video ID or part index')
    return f'https://www.bilibili.com/video/{video_id}?{urlencode({"p": index})}'


def parse_part_inventory(info: dict[str, Any], video_id: str) -> list[dict[str, Any]]:
    """Convert an yt-dlp playlist/single-video result to a validated part list."""
    kind = info.get('_type')
    if kind == 'playlist':
        entries = info.get('entries')
        if entries is None:
            raise ValueError('Playlist returned no entries: refusing incomplete inventory')
        entries = list(entries)
        count = info.get('playlist_count')
        if count is not None and int(count) != len(entries):
            raise ValueError(f'Partial part inventory ({len(entries)}/{count})')
        if not entries:
            raise ValueError('Playlist has no parts')
        parts = []
        for i, item in enumerate(entries, 1):
            if not isinstance(item, dict):
                raise ValueError(f'Part {i} is missing')
            url = item.get('url') or item.get('webpage_url') or ''
            # Only accept the same submission and the expected ?p=N ordering.
            match = re.search(r'[?&]p=(\d+)(?:[&#]|$)', str(url))
            if match and int(match.group(1)) != i:
                raise ValueError('Unexpected part order in playlist')
            if not str(url).startswith(f'https://www.bilibili.com/video/{video_id}'):
                raise ValueError(f'Part {i} is not a URL for submission {video_id}')
            parts.append({
                'part_index': i, 'cid': item.get('cid'), 'title': item.get('title') or '',
                'duration_seconds': item.get('duration'), 'url': part_url(video_id, i),
                'raw_metadata': {'id': item.get('id'), 'title': item.get('title'), 'cid': item.get('cid')},
            })
        return parts
    if kind in (None, 'video'):
        return [{'part_index': 1, 'cid': info.get('cid'), 'title': info.get('title') or '',
                 'duration_seconds': info.get('duration'), 'url': part_url(video_id, 1),
                 'raw_metadata': {'id': info.get('id'), 'cid': info.get('cid')}}]
    raise ValueError(f'Unsupported submission structure {kind!r}; cannot guarantee coverage')


def discover_parts(video_id: str, settings) -> list[dict[str, Any]]:
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError('Install yt-dlp to discover video parts') from exc
    from .ytdlp_adapter import _ydl_options

    opts = {**_ydl_options(settings, settings.artifacts_dir / 'part-inventory'),
            'noplaylist': False, 'extract_flat': 'in_playlist', 'skip_download': True,
            'ignoreerrors': False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(part_url(video_id, 1).split('?')[0], download=False)
    if not info:
        raise ValueError('Could not enumerate submission parts')
    return parse_part_inventory(info, video_id)
