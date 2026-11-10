from __future__ import annotations

import hashlib
import re
from html import unescape
from pathlib import Path


_TIME_RE = re.compile(
    r"(?P<start>(?:\d{2}:)?\d{2}:\d{2}[,.]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}[,.]\d{3})(?:.*)?"
)


def _normalise_time(value: str) -> str:
    value = value.replace(",", ".")
    return f"00:{value}" if value.count(":") == 1 else value


def parse_srt(raw_srt: str) -> list[dict[str, str]]:
    cues: list[dict[str, str]] = []
    blocks = re.split(r"\n\s*\n", raw_srt.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [line.strip("\ufeff ") for line in block.splitlines() if line.strip()]
        time_index = next((i for i, line in enumerate(lines) if _TIME_RE.match(line)), None)
        if time_index is None:
            continue
        match = _TIME_RE.match(lines[time_index])
        assert match is not None
        text_lines = lines[time_index + 1:]
        text = " ".join(text_lines).strip()
        text = re.sub(r"<[^>]+>", "", text)
        text = unescape(text)
        text = re.sub(r"\s+", " ", text)
        if text:
            cues.append({
                "start": _normalise_time(match.group("start")),
                "end": _normalise_time(match.group("end")),
                "text": text,
            })
    return cues


def cues_to_text(cues: list[dict[str, str]]) -> str:
    return "\n".join(
        f"[{cue['start']} - {cue['end']}] {cue['text']}" for cue in cues
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_vtt(raw_vtt: str) -> list[dict[str, str]]:
    # VTT cue blocks can include a WEBVTT header, cue identifiers, and NOTE blocks.
    cleaned = re.sub(r"(?m)^NOTE(?: .*?)?(?:\n(?:(?!\n).*)*)?", "", raw_vtt)
    return parse_srt(cleaned)


def read_subtitle(path: Path) -> tuple[str, str]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() == ".vtt":
        cues = parse_vtt(raw)
    else:
        cues = parse_srt(raw)
    return raw, cues_to_text(cues)


def read_srt(path: Path) -> tuple[str, str]:
    """Backward-compatible alias for SRT input."""
    return read_subtitle(path)


def seconds_to_srt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def cues_to_srt(cues: list[dict[str, object]]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        start = seconds_to_srt_time(float(cue["start"]))
        end = seconds_to_srt_time(float(cue["end"]))
        text = str(cue["text"]).strip()
        blocks.append(f"{index}\n{start} --> {end}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")
