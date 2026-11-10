from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from threading import Lock

from .subtitles import cues_to_srt

_model_init_lock = Lock()


@lru_cache(maxsize=4)
def _load_model(model_name: str, device: str, compute_type: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Install local ASR support: pip install -e '.[asr]'") from exc
    return WhisperModel(model_name, device=device, compute_type=compute_type)


def get_model(settings):
    """Per-process cached CTranslate2 model; initialization is synchronized."""
    with _model_init_lock:
        return _load_model(settings.whisper_model, settings.whisper_device, settings.whisper_compute_type)


def transcribe_audio(audio_path: Path, settings) -> tuple[str, str]:
    """Return (SRT, language) while reusing model weights for subsequent videos."""
    model = get_model(settings)
    language = getattr(settings, 'whisper_language', None) or None
    segments, info = model.transcribe(str(audio_path), vad_filter=True, language=language)
    cues = [
        {'start': segment.start, 'end': segment.end, 'text': segment.text.strip()}
        for segment in segments if segment.text.strip()
    ]
    return cues_to_srt(cues), getattr(info, 'language', language or 'und')
