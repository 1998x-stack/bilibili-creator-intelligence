# Verification matrix — v0.3.0 (2026-11-10)

Only offline simulated behavior is automated in CI; real Bilibili content, model weights, GPU environment and paid LLM API access are **not** exercised.

| Feature | Implemented source | Offline checks | Live caveat |
| --- | --- | --- | --- |
| Space discovery | `sources.py`, yt-dlp `BilibiliSpaceVideo` | Mocked playlist normalization, cap, audit | Unauthorized/private/hidden uploads may be missing; 352/412 possible |
| Multi-P completeness | `parts.py`, `pipeline.py`, `db.py` | Two-part assembly, malformed inventory, missing part prevents completion | Actual Bilibili pagination/cid access needs authorized E2E |
| Whisper model cache | `asr.py` | Monkeypatched model constructor reused | Local CPU/GPU memory and latency unbenchmarked |
| Durable queue | `queue.py`, `scheduler.py` | Concurrent atomic claims, lease renewal/fencing, exhaustion/retry | External side effects not exactly-once; multi-process workloads require stress tests |
| Token chunking and schema | `llm.py` with tiktoken, Pydantic | Unicode chunk round trip with fake encoder, strict missing-key rejection, fake API usage | Provider/model JSON Schema support not validated live |
| RPM/TPM and cost | `runtime.py`, `llm.py`, `llm_usage` | Fake API and usage accounting | Process-local only; billed failures may be unavailable; prices user supplied |
| Subtitle selection | `pipeline._choose_subtitle`, `SubtitleFile` | Source metadata + cue quality and fallback in local test | Coverage proxy is not measured accuracy |
| Search/exports | `transcript_segments_fts`, `db.export_jsonl` | Chinese search and latest transcript-to-analysis consistency | Legacy v0.2 transcripts not automatically backfilled |
| Metadata redaction | `security.sanitize_metadata` | Provider payload field allowlisting | Formal security review recommended |

Authoritative references:
- [yt-dlp Bilibili extractor](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/bilibili.py) (includes anthology page lists via `x/player/pagelist` and `?p=` links).
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper): model caching and `vad_filter` usage.
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs): Schema strict vs JSON mode.
- [SQLite WAL](https://www.sqlite.org/wal.html) and [FTS5 trigram tokenizer](https://www.sqlite.org/fts5.html).

Run: `python -m compileall -q src && python -m pytest -q` with no remote credentials. For a live smoke test with proper rights, start with `bci run --max-videos 1 --metadata-only --authorized-content-use` and only then enable ASR/LLM for one short submission.
