"""Complete-part transcript pipeline. No incomplete anthology is stored as 'complete'."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .asr import transcribe_audio
from .db import Database
from .llm import PROMPT_VERSION, analyze_transcript, to_markdown
from .parts import discover_parts
from .subtitles import parse_srt, parse_vtt, read_subtitle, sha256_text, cues_to_srt
from .ytdlp_adapter import download_audio, download_subtitles, extract_metadata, info_to_video_update


_LANG_PRIORITY = ('zh-cn', 'zh-hans', 'zh', 'ai-zh', 'zh-hant', 'en', 'ai-en')


def _seconds(value: str) -> float:
    h, m, s = value.replace(',', '.').split(':')
    return 3600 * int(h) + 60 * int(m) + float(s)


def _choose_subtitle(candidates: list, duration: float | None = None):
    """Validate content and prefer language, human tracks, temporal coverage and format.

    The returned asset may be Path (legacy/mock) or SubtitleFile with metadata.
    """
    scored = []
    for candidate in candidates:
        path = candidate.path if hasattr(candidate, 'path') else candidate
        if path.suffix.lower() not in {'.srt', '.vtt'}:
            continue
        try:
            raw = path.read_text(encoding='utf-8-sig', errors='replace')
            cues = parse_vtt(raw) if path.suffix.lower() == '.vtt' else parse_srt(raw)
        except (OSError, UnicodeError, ValueError):
            continue
        if not cues:
            continue
        language = getattr(candidate, 'language', None) or path.stem.split('.')[-1]
        group = getattr(candidate, 'source_group', None)
        lower = language.lower()
        language_priority = next((i for i, marker in enumerate(_LANG_PRIORITY)
                                  if lower == marker or lower.startswith(marker + '-')), 20)
        auto = lower.startswith('ai-') or group == 'automatic_captions'
        last_end = max(_seconds(c['end']) for c in cues)
        coverage = min(1.0, last_end / duration) if duration and duration > 0 else None
        quality = (coverage if coverage is not None else 1.0)
        # A track spanning <25% of the recording is suspiciously incomplete.
        if quality < 0.25:
            continue
        scored.append(((language_priority, int(auto), -quality, -len(cues),
                        0 if path.suffix.lower() == '.srt' else 1), candidate))
    return min(scored, key=lambda x: x[0])[1] if scored else None


def _write_artifact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')


def _stage_call(sem, func, *args):
    if sem is None:
        return func(*args)
    with sem:
        return func(*args)


def _collect_parts(db: Database, video_id: str, url: str, settings,
                   *, authorized_content_use: bool, fetch_subtitles: bool,
                   run_asr: bool, limits=None) -> None:
    parts = db.get_parts(video_id)
    if not parts:
        if not authorized_content_use:
            raise PermissionError('Part inventory requires authorized Bilibili access')
        inventory = _stage_call(getattr(limits, 'network', None), discover_parts, video_id, settings)
        db.upsert_parts(video_id, inventory)
        parts = db.get_parts(video_id)
    completed = db.get_part_transcripts(video_id)
    for part in parts:
        index = int(part['part_index'])
        if index in completed:
            continue
        part_url = part['url']
        part_dir = settings.artifacts_dir / video_id / 'parts' / f'p{index:03d}'
        subdir = part_dir / 'subtitles'
        if not authorized_content_use and (fetch_subtitles or run_asr):
            raise PermissionError('Remote subtitles/audio require authorization')
        selected = None
        if fetch_subtitles:
            db.log_job(video_id, f'subtitle:p{index}', 'running')
            try:
                candidates = _stage_call(getattr(limits, 'network', None), download_subtitles,
                                         part_url, settings, subdir)
                selected = _choose_subtitle(candidates, part['duration_seconds'])
                db.log_job(video_id, f'subtitle:p{index}', 'success' if selected else 'empty',
                           str(getattr(selected, 'path', selected)) if selected else 'No suitable subtitle')
            except Exception as exc:
                db.log_job(video_id, f'subtitle:p{index}', 'failed', repr(exc))
        if selected:
            path = selected.path if hasattr(selected, 'path') else selected
            raw, text = read_subtitle(path)
            if text.strip():
                lang = getattr(selected, 'language', None) or path.stem.split('.')[-1]
                source = ('automatic_caption' if lang.lower().startswith('ai-') or
                          getattr(selected, 'source_group', '') == 'automatic_captions'
                          else 'bilibili_subtitle')
                db.add_part_transcript(video_id, index, source, lang, text, raw,
                                       str(path), sha256_text(text), path.suffix.lstrip('.'))
                continue
        if run_asr:
            db.log_job(video_id, f'asr:p{index}', 'running')
            try:
                audio = _stage_call(getattr(limits, 'network', None), download_audio,
                                    part_url, settings, part_dir / 'audio')
                raw, language = _stage_call(getattr(limits, 'asr', None), transcribe_audio,
                                            audio, settings)
                target = subdir / f'{video_id}.p{index}.whisper.srt'
                _write_artifact(target, raw)
                _, text = read_subtitle(target)
                if not text.strip():
                    raise RuntimeError(f'ASR generated empty transcript for part {index}')
                db.add_part_transcript(video_id, index, 'faster_whisper', language,
                                       text, raw, str(target), sha256_text(text))
                db.log_job(video_id, f'asr:p{index}', 'success', f'language={language}')
            except Exception as exc:
                db.log_job(video_id, f'asr:p{index}', 'failed', repr(exc))
                raise
        else:
            raise RuntimeError(f'Part {index} has no usable transcript and ASR is disabled')


def _assemble_complete_transcript(db: Database, video_id: str) -> None:
    parts = db.get_parts(video_id)
    completed = db.get_part_transcripts(video_id)
    if not parts or set(completed) != {int(p['part_index']) for p in parts}:
        raise RuntimeError('Not all parts have transcripts; refusing partial assembly')
    all_cues, combined_srt, text = [], [], []
    offset = 0.0
    sources = set()
    for part in parts:
        index = int(part['part_index'])
        trans = completed[index]
        sources.add(trans['source'])
        cues = parse_vtt(trans['raw_subtitle']) if trans['format']=='vtt' else parse_srt(trans['raw_subtitle'])
        if not cues:
            raise ValueError(f'Part {index} has no valid timecoded subtitle cues')
        text.append(f'## PART {index}: {part["title"]}')
        for cue in cues:
            start, end = _seconds(cue['start']), _seconds(cue['end'])
            text.append(f'[P{index} {cue["start"]} - {cue["end"]}] {cue["text"]}')
            all_cues.append({'part_index':index,'start_ms':round(start*1000),
                             'end_ms':round(end*1000),'text':cue['text']})
            combined_srt.append({'start':offset + start,'end':offset + end,'text':f'[P{index}] {cue["text"]}'})
        offset += max(float(part['duration_seconds'] or 0), max(_seconds(c['end']) for c in cues))
    full_text = '\n'.join(text)
    digest = sha256_text(full_text)
    source = next(iter(sources)) if len(sources)==1 else 'mixed'
    languages = {t['language'] for t in completed.values() if t['language']}
    language = next(iter(languages)) if len(languages) == 1 else 'multi'
    transcript_id = db.add_transcript(video_id, source, language, full_text,
                                      cues_to_srt(combined_srt), None, digest)
    db.add_segments(transcript_id, all_cues)


def process_video(db: Database, video: Any, settings, *, authorized_content_use: bool,
                  fetch_metadata: bool = False, fetch_subtitles: bool = True,
                  run_asr: bool = True, run_llm: bool = True, limits=None) -> None:
    video_id, url, creator_mid = video['video_id'], video['url'], video['creator_mid']
    needs_remote = fetch_metadata or ((fetch_subtitles or run_asr) and
                                       (not db.get_parts(video_id) or len(db.get_part_transcripts(video_id)) < len(db.get_parts(video_id))))
    if needs_remote and not authorized_content_use:
        raise PermissionError('Remote processing requires --authorized-content-use and actual permission')
    if fetch_metadata:
        info = _stage_call(getattr(limits, 'network', None), extract_metadata, url, settings)
        db.upsert_video(info_to_video_update(info, creator_mid, url, requested_video_id=video_id))
    if fetch_subtitles or run_asr:
        _collect_parts(db, video_id, url, settings, authorized_content_use=authorized_content_use,
                       fetch_subtitles=fetch_subtitles, run_asr=run_asr, limits=limits)
        _assemble_complete_transcript(db, video_id)

    if not run_llm:
        return
    transcript = db.latest_transcript(video_id)
    if transcript is None:
        db.log_job(video_id, 'llm', 'skipped', 'No complete transcript')
        return
    if db.analysis_exists(video_id, transcript['content_sha256'], settings.llm_model, PROMPT_VERSION):
        db.log_job(video_id, 'llm', 'skipped', 'Cached result')
        return
    db.log_job(video_id, 'llm', 'running')
    try:
        # Direct callers and existing tests can run without the scheduler object.
        if limits is None:
            result = analyze_transcript(transcript['transcript_text'], settings)
        else:
            result = analyze_transcript(transcript['transcript_text'], settings,
                                        db=db, video_id=video_id, limits=limits)
        markdown = to_markdown(result)
        analysis_dir = settings.artifacts_dir / video_id / 'analysis'
        _write_artifact(analysis_dir / 'analysis.json', json.dumps(result, ensure_ascii=False, indent=2))
        _write_artifact(analysis_dir / 'analysis.md', markdown)
        db.add_analysis(video_id, int(transcript['id']), transcript['content_sha256'],
                        'openai-compatible', settings.llm_model, PROMPT_VERSION, result, markdown)
        db.log_job(video_id, 'llm', 'success', settings.llm_model)
    except Exception as exc:
        db.log_job(video_id, 'llm', 'failed', repr(exc))
        raise
