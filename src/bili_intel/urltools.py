from __future__ import annotations

import re
from urllib.parse import urlparse


_MID_RE = re.compile(r"^/(\d+)(?:/|$)", re.IGNORECASE)
_BVID_RE = re.compile(r"\b(BV[0-9A-Za-z]{10})\b")
_AV_RE = re.compile(r"(?:^|/)video/av(\d+)(?:/|$)", re.IGNORECASE)


def extract_mid(space_url: str) -> str:
    """Extract a numeric creator MID from a Bilibili space URL."""
    parsed = urlparse(space_url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
        "space.bilibili.com",
        "www.space.bilibili.com",
    }:
        raise ValueError(f"Not a Bilibili space URL: {space_url}")
    match = _MID_RE.search(parsed.path)
    if not match:
        raise ValueError(f"Could not extract creator MID from: {space_url}")
    return match.group(1)


def extract_video_id(video_url: str) -> str:
    """Extract a BV id or legacy AV id from a Bilibili video URL."""
    parsed = urlparse(video_url.strip())
    host = parsed.netloc.lower()
    if host not in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}:
        raise ValueError(f"Not a Bilibili video URL: {video_url}")
    bv_match = _BVID_RE.search(parsed.path + "?" + parsed.query)
    if bv_match:
        return bv_match.group(1)
    av_match = _AV_RE.search(parsed.path)
    if av_match:
        return f"av{av_match.group(1)}"
    raise ValueError(f"Could not extract BV/AV id from: {video_url}")


def canonical_video_url(video_id: str) -> str:
    if video_id.lower().startswith("av"):
        return f"https://www.bilibili.com/video/{video_id}/"
    if not video_id.startswith("BV"):
        raise ValueError(f"Unsupported video id: {video_id}")
    return f"https://www.bilibili.com/video/{video_id}/"
