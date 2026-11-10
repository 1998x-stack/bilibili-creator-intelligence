# Changelog

## 0.2.0 — 2026-11-10

- Bootstrap the repository from the locally tested prototype.
- Add optional space-URL discovery via yt-dlp's `BilibiliSpaceVideo` extractor with explicit authorization and fail-fast coverage handling.
- Add discovery-run auditing, JSONL export, incremental SQLite ingestion and CLI subcommands.
- Guarantee that a capped discovery run only processes videos returned by that run, not historical SQLite rows.
- Bound LLM chunking and hierarchical synthesis; filter sensitive metadata before persistence.
- Add reproducible offline tests, GitHub Actions CI, security documentation and bilingual usage guides.
