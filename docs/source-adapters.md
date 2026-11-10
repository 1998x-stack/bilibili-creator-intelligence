# Video discovery adapters and permissions

## Two supported sources

1. **Offline manifest** (`--source manifest` or `bci ingest`): a CSV of videos obtained through an authorized export or another legitimate source. No network access is needed to import it.
2. **yt-dlp BilibiliSpaceVideo** (`--source yt-dlp`): enumerates accessible video entries through yt-dlp's public Bilibili space extractor, which uses changing Bilibili web endpoints including WBI behind the scenes. Explicit `--authorized-content-use` is mandatory, but that switch **does not** grant consent, override Bilibili terms, or promise coverage.

The Bilibili space URL itself only encodes MID. Neither the local parser nor yt-dlp's playlist count can establish that all the creator's uploads are public and accessible. yt-dlp can be refused with 352/412 or its interface can break. The adapter fails loudly on malformed/unknown video entries. If `--max-videos` is used, the report declares `complete=false`; without a cap, completeness is **unknown** (not true).

## Official Open Platform

Bilibili documents a user-authorized single-archive API at `GET https://member.bilibili.com/arcopen/fn/archive/view?resource_id=...`, requiring `ARC_BASE` permission and the platform's signed authentication headers. Community-mirrored Open Platform documentation also describes `GET /arcopen/fn/archive/viewlist` for user-authorized archive lists (up to 50 per page); use that only after validating permissions and current official signature rules for your registered application. An official adapter is intentionally left as a tested extension point, not fabricated as anonymous read access.

## Metadata provenance

- yt-dlp's Bilibili extractor exposes many common video fields, but not all engagement counters in every case.
- Unknown counters are stored as SQL `NULL`. A valid zero remains `0`.
- `video_stats` creates timestamped snapshots. Source metadata is filtered to a safe allowlist before SQLite persistence, excluding stream URL signatures, cookies, downloaded format structures and HTTP headers.
- A creator may republish or delete material; never infer permanent absence merely because one discovery run returned fewer results.

## Operational policy

Use permissioned sources, a conservative request rate, no bypass of restrictions, and a local cache. Do not expose cookies or developer credentials. Keep ASR and transcripts local unless an operator has deliberately enabled an LLM provider. A future official adapter must test response normalization with redacted fixtures and confirm scope/rate limits.
