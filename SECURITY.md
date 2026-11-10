# Security policy

Never commit `.env`, Bilibili cookies, access tokens, audio/video recordings, local SQLite databases, or transcripts containing private content. All are ignored under `data/` and by the repository's credential-file patterns. The pipeline requires explicit `--authorized-content-use` before remote discovery/processing; this confirmation does **not** confer legal permission. Respect Bilibili terms, IP blocks, rate limits, takedown requests and creator consent. Do not use the project to bypass authentication, CAPTCHA or access controls.

Use a private disclosure to the repository maintainers for suspected vulnerabilities. Include a reproduction without real tokens or personal data. Transcripts sent to a third-party LLM leave the local machine; use `--no-llm` when privacy is required.
