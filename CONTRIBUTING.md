# Contributing

Use Python 3.11+ and an isolated virtual environment. Run `python -m pytest -q` and `python -m compileall -q src` before opening a PR. Add offline mock tests for discovery, persistence and network adapters: CI must not contact Bilibili, download audio, invoke ASR or charge for LLM usage.

Avoid undocumented authentication bypasses and invasive scraping. Keep the `CreatorVideoSource` boundary explicit, distinguish unknown counters (`NULL`) from zero, and preserve provenance for text and AI results. Treat changes to the SQLite schema as migrations and add tests that open existing databases.
