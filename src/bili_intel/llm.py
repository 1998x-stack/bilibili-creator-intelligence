from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROMPT_VERSION = "video-analysis-v2"


def _read_prompt() -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / "video_analysis.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return (
        "Analyze only the supplied transcript. Do not invent facts. Use timestamps as evidence. "
        "Return valid JSON with executive_summary, core_thesis, key_points, concepts, "
        "arguments_and_evidence, conclusions, actionable_takeaways, outline, notable_quotes, "
        "uncertainty_and_gaps, and tags."
    )


def _chunks(text: str, max_chars: int) -> list[str]:
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        # Very long subtitle cues must also be split; never exceed the requested budget.
        pieces = [line[i:i + max_chars] for i in range(0, len(line), max_chars)] or [""]
        for piece in pieces:
            if current and current_len + len(piece) + 1 > max_chars:
                chunks.append("\n".join(current))
                current, current_len = [], 0
            current.append(piece)
            current_len += len(piece) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks or [text]


def _client():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install LLM support: pip install -e '.[llm]'") from exc
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    base_url = os.getenv("OPENAI_BASE_URL") or None
    return OpenAI(api_key=api_key, base_url=base_url)


_REQUIRED_LIST_FIELDS = (
    "key_points", "concepts", "arguments_and_evidence", "conclusions",
    "actionable_takeaways", "outline", "notable_quotes", "uncertainty_and_gaps", "tags",
)


def _validate_result(content: str) -> dict[str, Any]:
    """Parse JSON mode output and validate the minimal application contract."""
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError("LLM output must be a JSON object")
    result.setdefault("title", "")
    result.setdefault("executive_summary", "")
    result.setdefault("core_thesis", "")
    for field in _REQUIRED_LIST_FIELDS:
        result.setdefault(field, [])
        if not isinstance(result[field], list):
            raise ValueError(f"LLM output field {field!r} must be a list")
    return result


def analyze_transcript(text: str, settings) -> dict[str, Any]:
    """Chunk long transcripts, summarize each chunk, then synthesize a final JSON result."""
    if not text.strip():
        raise ValueError("Transcript has no content")
    client = _client()
    model = settings.llm_model
    system_prompt = _read_prompt()
    chunks = _chunks(text, settings.llm_max_chars)
    chunk_notes: list[str] = []

    for index, chunk in enumerate(chunks, start=1):
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt + "\nFor this step, return a compact JSON analysis of this transcript segment."},
                {"role": "user", "content": f"Segment {index}/{len(chunks)}:\n{chunk}"},
            ],
        )
        content = response.choices[0].message.content or "{}"
        chunk_notes.append(content)

    # Hierarchical reduction to prevent an unbounded final prompt on long creators' videos.
    # The hierarchy bounds the fan-in by two, even if individual model outputs are verbose.
    while len(chunk_notes) > 1:
        next_level: list[str] = []
        for i in range(0, len(chunk_notes), 2):
            pair = chunk_notes[i:i + 2]
            if len(pair) == 1:
                next_level.append(pair[0])
                continue
            response = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt +
                     "\nMerge these two segment analyses into a coherent JSON object. "
                     "Preserve evidence timestamps, avoid unsupported claims and duplication."},
                    {"role": "user", "content": "Analyses to merge:\n" + "\n\n".join(pair)},
                ],
            )
            next_level.append(response.choices[0].message.content or "{}")
        chunk_notes = next_level
    return _validate_result(chunk_notes[0])


def to_markdown(result: dict[str, Any]) -> str:
    lines = [f"# {result.get('title') or '视频核心内容'}", ""]
    summary = result.get("executive_summary")
    if summary:
        lines += ["## 摘要", str(summary), ""]
    thesis = result.get("core_thesis")
    if thesis:
        lines += ["## 核心论点", str(thesis), ""]
    for section, key, fields in [
        ("核心观点", "key_points", ("point", "explanation", "evidence_timestamps")),
        ("关键概念", "concepts", ("term", "explanation")),
        ("论据与证据", "arguments_and_evidence", ("claim", "evidence", "evidence_timestamps", "caveats")),
        ("结论", "conclusions", ()),
        ("可执行启发", "actionable_takeaways", ()),
        ("视频结构", "outline", ("section", "start_timestamp", "end_timestamp", "summary")),
        ("值得引用的原话", "notable_quotes", ("quote", "timestamp")),
        ("不确定性与信息缺口", "uncertainty_and_gaps", ()),
        ("标签", "tags", ()),
    ]:
        values = result.get(key) or []
        if not values:
            continue
        lines += [f"## {section}"]
        for item in values:
            if isinstance(item, dict):
                title = item.get(fields[0], "") if fields else ""
                lines.append(f"- **{title}**" if title else "-")
                for field in fields[1:]:
                    value = item.get(field)
                    if value not in (None, "", []):
                        lines.append(f"  - {field}: {value}")
            else:
                lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
