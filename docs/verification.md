# Verification matrix (2026-11-10)

This file separates **verified source capabilities** from **locally tested behavior** and **not-yet-verified live integration**.

| Stage | Evidence | Local automated checks | Live limitations |
| --- | --- | --- | --- |
| Space URL → creator MID | Local URL validation code | Accepts known MID format, rejects wrong hosts | Does not verify MID exists |
| yt-dlp space discovery | [SupportedSites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) lists `BilibiliSpaceVideo`; [extractor source](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/bilibili.py) contains its playlist logic | Fake playlist, dedupe, MID consistency, cap, incomplete/malformed rejection | Can receive 352/412, inaccessible uploads missing, live E2E not run |
| Official API authorization | [Official single archive API](https://openhome.bilibili.com/doc/4/d9554788-dcef-f139-6217-b487d41c3826) requires `ARC_BASE` and user consent; [mirrored list API](https://bilibili.apifox.cn/api-23727647) | Official adapter intentionally not called or falsely simulated | Requires registered app, approved scopes, signed headers |
| Metrics and SQLite | yt-dlp [Bilibili extractor source](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/bilibili.py) exposes likes/views/comments | Sparse merge, missing is NULL, zero is zero, snapshots, JSONL export | `coin/favorite/share` often unavailable from yt-dlp |
| Subtitles | [yt-dlp subtitles documentation](https://github.com/yt-dlp/yt-dlp#subtitle-options); [Bilibili AI subtitle issue](https://github.com/yt-dlp/yt-dlp/issues/14463) | SRT/VTT parser, generated timecodes, mocked subtitle preference | Actual subtitle availability varies; login may be required |
| Audio + ASR | [yt-dlp FFmpeg](https://github.com/yt-dlp/yt-dlp), [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Mocked fallback when no subtitles | No real audio downloaded; ffmpeg/weights/hardware untested |
| LLM synthesis | [OpenAI JSON response documentation](https://platform.openai.com/docs/guides/structured-outputs) | Bounded transcript chunks, JSON contract validation, mocked cache | Model compatibility and output quality not tested live; JSON mode is not strict schema validation |
| CI and packaging | Python setuptools project and GitHub Actions workflow in repo | `python -m pytest -q`; `python -m compileall -q src` | CI must run on GitHub for cross-version verification |

The automated test suite deliberately requires no credentials, network or LLM billing. Live behavior must be validated separately using an authorized creator and a small sample, starting with `bci discover` and `bci run --max-videos 1 --metadata-only`.
