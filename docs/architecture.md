# Architecture and data integrity

## Pipeline

`space URL → source adapter (CSV or opt-in yt-dlp) → videos + engagement snapshots → original SRT subtitles → audio-only ASR fallback → chunked JSON LLM analysis → local SQLite → JSONL export`

The URL parser is offline. Discovery (`discover`) is independent of processing (`process`), so the scan can be followed by a series of capped, retryable processing batches. `run` combines both. A failed discovery records a failed `discovery_runs` row, without erasing previously discovered videos. New entries are upserted by video ID.

## SQLite entities

- `creators`: creator MID identity and source information.
- `videos`: stable BV/AV key and text metadata. Empty title/description from a sparse playlist cannot overwrite known nonempty values.
- `video_stats`: one append-oriented snapshot per `(video_id, captured_at)`. All counters are nullable.
- `transcripts`: dedupe by `(video_id, SHA-256 timestamped transcript)`; source distinguishes original Bilibili subtitles and local ASR.
- `analyses`: unique by `(video_id, transcript_sha256, model, prompt_version)`. Output JSON and Markdown are local artifacts, not publication-ready facts.
- `discovery_runs`: audit of source, status, scanned video count and caveats.
- `jobs`: stage-level event log for subtitle, ASR and LLM phases. A new event is inserted on each transition.

## Error and cost model

All videos are processed sequentially to avoid request bursts; yt-dlp discovery uses one-second request spacing. Subtitle failures can fall back to ASR, but ASR and LLM failures are not swallowed. No text means LLM is skipped. Only the transcript and configured model/prompt combination trigger a new analysis. `--metadata-only`, `--no-asr`, and `--no-llm` limit bandwidth, compute and API costs.

An oversized transcript cue is split into bounded character chunks. Chunk responses are combined pairwise, so the final synthesis does not concatenate an unbounded number of segments. JSON output is validated for expected list fields; this is **not** a guarantee of factual correctness. Evidence timestamps should be checked against the recording.

## Unimplemented (tracked separately)

- Full multi-P subtitle/ASR extraction for every part of an archive.
- An app-registered, officially signed Open Platform `viewlist` adapter with validated token lifecycle.
- Live Bilibili and model integration tests with dedicated authorized test accounts.
- Schema migrations beyond additive v0.2 tables and automated backups.
