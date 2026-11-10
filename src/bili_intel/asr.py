from __future__ import annotations

from pathlib import Path

from .subtitles import cues_to_srt


def transcribe_audio(audio_path: Path, settings) -> tuple[str, str]:
    """Return (SRT text, detected language) using local faster-whisper."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Install local ASR support: pip install -e '.[asr]'") from exc

    model = WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    segments, info = model.transcribe(str(audio_path), vad_filter=True)
    cues = [
        {"start": segment.start, "end": segment.end, "text": segment.text.strip()}
        for segment in segments
        if segment.text.strip()
    ]
    return cues_to_srt(cues), getattr(info, "language", "und")
