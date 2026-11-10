# Bilibili Creator Intelligence

**Local-first Bilibili creator analytics and transcript knowledge pipeline — v0.3.0**

Authorized creator URL / CSV → video discovery → engagement snapshots → **every accessible video part** (`?p=N`) → source subtitles or cached local faster-whisper → structured, token-budgeted LLM analysis → SQLite with full-text segment search and JSONL export.

[中文说明](README.zh.md) · [Architecture](docs/architecture.md) · [Source policy](docs/source-adapters.md) · [Verification](docs/verification.md) · [Security](SECURITY.md)

> The yt-dlp creator-space extractor uses an **unofficial** Bilibili endpoint. `--authorized-content-use` is an operator declaration, not a grant of rights. Discovery and accessible content may be incomplete, and the project does not bypass access controls or platform safeguards.

## Installation

```bash
# macOS: brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[all,dev]'
cp .env.example .env
```

Set `OPENAI_API_KEY` for LLM analysis, plus any optional `OPENAI_BASE_URL` and `BCI_LLM_MODEL`. faster-whisper is local; for CPU the conservative configuration is `BCI_WHISPER_DEVICE=cpu` and `BCI_WHISPER_COMPUTE_TYPE=int8`. It does not automatically provide Apple MPS acceleration. The default model is `small` and may download weights on first use.

```bash
bci run --space-url 'https://space.bilibili.com/123456/video' \
  --source yt-dlp --authorized-content-use --max-videos 1 --metadata-only

bci run --space-url 'https://space.bilibili.com/123456/video' \
  --source yt-dlp --authorized-content-use --max-videos 1

# Alternative: import an authorized CSV list
bci ingest --space-url 'https://space.bilibili.com/123456/video' \
  --manifest examples/videos.csv
bci process --mid 123456 --authorized-content-use --limit 10

bci queue-status
bci costs
bci stats
bci search '知识点分析'
bci export --mid 123456 --output data/export/creator.jsonl
```

## What's implemented

- Multi-P part inventory and completeness checks; per-part subtitle / ASR artifacts and full-video synthesis only after **all** parts complete.
- In-process Whisper model cache and CPU/GPU stage semaphores.
- SQLite WAL job queue: atomic task claims, fencing tokens, heartbeat, abandoned task recovery, bounded retries and exponential backoff.
- Token-aware chunking (tiktoken), hierarchical map-reduce, output budgets, **Pydantic JSON Schema** Structured Outputs (default) with explicitly selectable validated JSON mode.
- Process-local network/ASR/LLM concurrency caps plus LLM RPM/TPM admissions; LLM token usage and optional estimated USD cost/budget tracking.
- Subtitle language/source/coverage assessment; timestamped FTS5 trigram search with video part and millisecond offsets.
- Prompt + schema fingerprint in the cache key, safe metadata allowlists, and transcript-matched analysis export.

`BCI_WORKERS`, `BCI_NETWORK_WORKERS`, `BCI_ASR_WORKERS`, `BCI_LLM_WORKERS`, `BCI_LLM_RPM` and `BCI_LLM_TPM` are configurable in `.env`. Provider-specific pricing is deliberately **not guessed**; optional `BCI_LLM_INPUT_USD_PER_MTOK`, `BCI_LLM_OUTPUT_USD_PER_MTOK`, and `BCI_LLM_BUDGET_USD` must be configured together for estimated budget enforcement. Such limits are **process-local**, not centralized across multiple installations or multiple API callers. Failed requests may still incur a charge.

For older OpenAI-compatible services without strict JSON Schema response support, explicitly set `BCI_LLM_MODE=json`; outputs are still locally validated. The default mode does **not** silently downgrade. `BCI_LLM_MAX_INPUT_TOKENS` and `BCI_LLM_MAX_OUTPUT_TOKENS` configure the LLM budget; `BCI_LLM_MAX_CHARS` is retained for backwards compatibility but no longer used to slice LLM input.

Use `bci process --mid ... --retry-failed` to explicitly requeue exhausted work. On crashes, re-invoking process preserves pending leases/attempts. Jobs are not exactly-once with respect to external network/API side effects. Use `--queue-only` to stage tasks without executing them. Run with `--no-llm` to ensure no subtitle text is sent to an external LLM.

**Known boundaries:** creator discovery can fail or be incomplete; coin/favorite/share counters can be unavailable (`NULL`, not zero); interactive/unsupported playlist types are rejected; no real Bilibili/Whisper/LLM end-to-end test is claimed by the offline test suite. Only SQLite and local artifacts are retained by default; full MP4s are not downloaded.

See [architecture](docs/architecture.md) and [verification matrix](docs/verification.md) for implementation details and remaining gaps. MIT licensed.
