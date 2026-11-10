from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .security import sanitize_metadata


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS creators (
    mid TEXT PRIMARY KEY,
    space_url TEXT NOT NULL,
    name TEXT,
    sign TEXT,
    source_provider TEXT NOT NULL DEFAULT 'manifest',
    raw_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    creator_mid TEXT NOT NULL REFERENCES creators(mid) ON DELETE CASCADE,
    bvid TEXT,
    aid TEXT,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    pubdate TEXT,
    duration_seconds REAL,
    category TEXT,
    cover_url TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    raw_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_videos_creator_mid ON videos(creator_mid);
CREATE INDEX IF NOT EXISTS idx_videos_pubdate ON videos(pubdate);

CREATE TABLE IF NOT EXISTS video_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    captured_at TEXT NOT NULL,
    view_count INTEGER,
    like_count INTEGER,
    coin_count INTEGER,
    favorite_count INTEGER,
    share_count INTEGER,
    danmaku_count INTEGER,
    comment_count INTEGER,
    raw_stats_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(video_id, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_stats_video_captured ON video_stats(video_id, captured_at DESC);

CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    language TEXT,
    format TEXT NOT NULL DEFAULT 'srt',
    transcript_text TEXT NOT NULL,
    raw_subtitle TEXT,
    artifact_path TEXT,
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(video_id, content_sha256)
);
CREATE INDEX IF NOT EXISTS idx_transcripts_video ON transcripts(video_id, created_at DESC);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    transcript_id INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    transcript_sha256 TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    result_json TEXT NOT NULL,
    result_markdown TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(video_id, transcript_sha256, model, prompt_version)
);
CREATE INDEX IF NOT EXISTS idx_analyses_video ON analyses(video_id, created_at DESC);

CREATE TABLE IF NOT EXISTS discovery_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_mid TEXT NOT NULL REFERENCES creators(mid) ON DELETE CASCADE,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    found_count INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_discovery_creator ON discovery_runs(creator_mid, started_at DESC);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_video ON jobs(video_id, started_at DESC);

-- A submission may contain many distinct p=N parts (and distinct CIDs).
CREATE TABLE IF NOT EXISTS video_parts (
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    part_index INTEGER NOT NULL CHECK(part_index >= 1),
    cid TEXT,
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    duration_seconds REAL,
    raw_metadata_json TEXT NOT NULL DEFAULT '{}',
    discovered_at TEXT NOT NULL,
    PRIMARY KEY (video_id, part_index)
);
CREATE TABLE IF NOT EXISTS part_transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    part_index INTEGER NOT NULL,
    source TEXT NOT NULL,
    language TEXT,
    format TEXT NOT NULL DEFAULT 'srt',
    transcript_text TEXT NOT NULL,
    raw_subtitle TEXT,
    artifact_path TEXT,
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (video_id,part_index) REFERENCES video_parts(video_id,part_index) ON DELETE CASCADE,
    UNIQUE(video_id,part_index,content_sha256)
);
CREATE INDEX IF NOT EXISTS idx_part_transcript ON part_transcripts(video_id,part_index,id DESC);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transcript_id INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL,
    part_index INTEGER NOT NULL CHECK(part_index >= 1),
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL,
    UNIQUE(transcript_id,segment_index)
);
CREATE INDEX IF NOT EXISTS idx_segments_transcript ON transcript_segments(transcript_id,start_ms);
CREATE VIRTUAL TABLE IF NOT EXISTS transcript_segments_fts USING fts5(
    text, content='transcript_segments', content_rowid='id', tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON transcript_segments BEGIN
    INSERT INTO transcript_segments_fts(rowid,text) VALUES(new.id,new.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON transcript_segments BEGIN
    INSERT INTO transcript_segments_fts(transcript_segments_fts,rowid,text)
    VALUES('delete',old.id,old.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE ON transcript_segments BEGIN
    INSERT INTO transcript_segments_fts(transcript_segments_fts,rowid,text)
    VALUES('delete',old.id,old.text);
    INSERT INTO transcript_segments_fts(rowid,text) VALUES(new.id,new.text);
END;

CREATE TABLE IF NOT EXISTS work_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at REAL NOT NULL,
    lease_until REAL,
    lease_token TEXT,
    last_error TEXT,
    updated_at REAL NOT NULL,
    batch_id TEXT,
    UNIQUE(video_id,stage)
);
CREATE INDEX IF NOT EXISTS idx_work_claim ON work_items(stage,status,available_at,lease_until);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT REFERENCES videos(video_id) ON DELETE SET NULL,
    stage TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    estimated_cost_usd REAL,
    duration_seconds REAL,
    status TEXT NOT NULL,
    error_type TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_date ON llm_usage(created_at);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)

    def upsert_creator(self, mid: str, space_url: str, raw: dict[str, Any] | None = None) -> None:
        now = utc_now()
        raw_json = json.dumps(sanitize_metadata(raw), ensure_ascii=False, default=str)
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO creators(mid, space_url, raw_metadata_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(mid) DO UPDATE SET space_url=excluded.space_url,
                   raw_metadata_json=excluded.raw_metadata_json, updated_at=excluded.updated_at""",
                (mid, space_url, raw_json, now, now),
            )

    def upsert_video(self, video: dict[str, Any]) -> None:
        now = utc_now()
        tags_json = json.dumps(video.get("tags") or [], ensure_ascii=False)
        raw_json = json.dumps(sanitize_metadata(video.get("raw_metadata")), ensure_ascii=False, default=str)
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO videos(
                    video_id, creator_mid, bvid, aid, title, description, url, pubdate,
                    duration_seconds, category, cover_url, tags_json, raw_metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    creator_mid=excluded.creator_mid, bvid=excluded.bvid, aid=excluded.aid,
                    title=COALESCE(NULLIF(excluded.title, ''), videos.title),
                    description=COALESCE(NULLIF(excluded.description, ''), videos.description),
                    url=excluded.url,
                    pubdate=COALESCE(excluded.pubdate, videos.pubdate),
                    duration_seconds=COALESCE(excluded.duration_seconds, videos.duration_seconds),
                    category=COALESCE(excluded.category, videos.category),
                    cover_url=COALESCE(excluded.cover_url, videos.cover_url),
                    tags_json=excluded.tags_json, raw_metadata_json=excluded.raw_metadata_json,
                    updated_at=excluded.updated_at""",
                (
                    video["video_id"], video["creator_mid"], video.get("bvid"), video.get("aid"),
                    video.get("title") or "", video.get("description") or "", video["url"],
                    video.get("pubdate"), video.get("duration_seconds"), video.get("category"),
                    video.get("cover_url"), tags_json, raw_json, now, now,
                ),
            )
        stats = video.get("stats") or {}
        if stats and any(value is not None for key, value in stats.items() if key != "captured_at"):
            self.add_stats(video["video_id"], stats, raw=video.get("raw_stats") or {})

    def add_stats(self, video_id: str, stats: dict[str, Any], raw: dict[str, Any] | None = None) -> None:
        captured_at = stats.get("captured_at") or utc_now()
        fields = (
            "view_count", "like_count", "coin_count", "favorite_count",
            "share_count", "danmaku_count", "comment_count",
        )
        values = [stats.get(field) for field in fields]
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO video_stats(
                    video_id, captured_at, view_count, like_count, coin_count,
                    favorite_count, share_count, danmaku_count, comment_count, raw_stats_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (video_id, captured_at, *values, json.dumps(raw or {}, ensure_ascii=False, default=str)),
            )

    def get_videos(self, creator_mid: str | None = None, video_id: str | None = None) -> list[sqlite3.Row]:
        with self.connect() as conn:
            if video_id:
                return list(conn.execute("SELECT * FROM videos WHERE video_id=?", (video_id,)))
            if creator_mid:
                return list(conn.execute(
                    "SELECT * FROM videos WHERE creator_mid=? ORDER BY pubdate DESC, video_id",
                    (creator_mid,),
                ))
            return list(conn.execute("SELECT * FROM videos ORDER BY pubdate DESC, video_id"))

    def add_transcript(
        self, video_id: str, source: str, language: str | None, transcript_text: str,
        raw_subtitle: str | None, artifact_path: str | None, content_sha256: str,
        subtitle_format: str = "srt",
    ) -> int:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO transcripts(
                    video_id, source, language, format, transcript_text, raw_subtitle,
                    artifact_path, content_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (video_id, source, language, subtitle_format, transcript_text, raw_subtitle, artifact_path,
                 content_sha256, utc_now()),
            )
            row = conn.execute(
                "SELECT id FROM transcripts WHERE video_id=? AND content_sha256=?",
                (video_id, content_sha256),
            ).fetchone()
            return int(row["id"])

    def latest_transcript(self, video_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM transcripts WHERE video_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
                (video_id,),
            ).fetchone()

    def analysis_exists(self, video_id: str, transcript_sha256: str, model: str, prompt_version: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM analyses WHERE video_id=? AND transcript_sha256=?
                   AND model=? AND prompt_version=? LIMIT 1""",
                (video_id, transcript_sha256, model, prompt_version),
            ).fetchone()
            return row is not None

    def add_analysis(
        self, video_id: str, transcript_id: int, transcript_sha256: str,
        provider: str, model: str, prompt_version: str,
        result: dict[str, Any], markdown: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO analyses(
                    video_id, transcript_id, transcript_sha256, provider, model,
                    prompt_version, result_json, result_markdown, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (video_id, transcript_id, transcript_sha256, provider, model,
                 prompt_version, json.dumps(result, ensure_ascii=False, default=str), markdown, utc_now()),
            )

    def log_job(self, video_id: str, stage: str, status: str, message: str | None = None) -> None:
        now = utc_now()
        with self.connect() as conn:
            finished_at = None if status == "running" else now
            conn.execute(
                "INSERT INTO jobs(video_id, stage, status, message, started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?)",
                (video_id, stage, status, message, now, finished_at),
            )

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("creators", "videos", "video_parts", "part_transcripts", "video_stats", "transcripts", "transcript_segments", "analyses", "discovery_runs", "jobs", "work_items", "llm_usage")
            }

    def start_discovery(self, mid: str, source: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO discovery_runs(creator_mid, source, status, started_at) VALUES (?, ?, 'running', ?)",
                (mid, source, utc_now()),
            )
            return int(cur.lastrowid)

    def finish_discovery(self, run_id: int, status: str, count: int, details: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE discovery_runs SET status=?, found_count=?, details_json=?, finished_at=?
                   WHERE id=?""",
                (status, count, json.dumps(details, ensure_ascii=False, default=str), utc_now(), run_id),
            )

    def export_jsonl(self, creator_mid: str, target: Path) -> int:
        """JSONL export includes the newest transcript/analysis and latest stat snapshot."""
        target.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with self.connect() as conn, target.open('w', encoding='utf-8') as out:
            for row in conn.execute('SELECT * FROM videos WHERE creator_mid=? ORDER BY pubdate DESC, video_id', (creator_mid,)):
                video_id = row['video_id']
                stats = conn.execute('SELECT * FROM video_stats WHERE video_id=? ORDER BY captured_at DESC,id DESC LIMIT 1', (video_id,)).fetchone()
                transcript = conn.execute('SELECT * FROM transcripts WHERE video_id=? ORDER BY id DESC LIMIT 1', (video_id,)).fetchone()
                analysis = conn.execute('SELECT * FROM analyses WHERE transcript_id=? ORDER BY id DESC LIMIT 1', (transcript['id'],)).fetchone() if transcript else None
                record = {
                    'video': dict(row),
                    'stats': dict(stats) if stats else None,
                    'transcript': dict(transcript) if transcript else None,
                    'analysis': dict(analysis) if analysis else None,
                }
                out.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
                count += 1
        return count

    def upsert_parts(self, video_id: str, parts: list[dict[str, Any]]) -> None:
        """Persist validated 1-based part inventory before downloading content."""
        if not parts or [p['part_index'] for p in parts] != list(range(1, len(parts) + 1)):
            raise ValueError('Parts must be a non-empty, contiguous 1-based inventory')
        now = utc_now()
        with self.connect() as conn:
            for part in parts:
                conn.execute(
                    """INSERT INTO video_parts(video_id,part_index,cid,title,url,duration_seconds,raw_metadata_json,discovered_at)
                       VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(video_id,part_index) DO UPDATE SET
                         cid=excluded.cid,title=excluded.title,url=excluded.url,
                         duration_seconds=excluded.duration_seconds,
                         raw_metadata_json=excluded.raw_metadata_json,discovered_at=excluded.discovered_at""",
                    (video_id, part['part_index'], str(part.get('cid')) if part.get('cid') is not None else None,
                     part.get('title') or '', part['url'], part.get('duration_seconds'),
                     json.dumps(part.get('raw_metadata') or {}, ensure_ascii=False), now),
                )

    def get_parts(self, video_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute('SELECT * FROM video_parts WHERE video_id=? ORDER BY part_index', (video_id,)))

    def add_part_transcript(self, video_id: str, part_index: int, source: str,
                            language: str | None, transcript_text: str,
                            raw_subtitle: str, artifact_path: str, digest: str,
                            subtitle_format: str = 'srt') -> int:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO part_transcripts(video_id,part_index,source,language,format,
                   transcript_text,raw_subtitle,artifact_path,content_sha256,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (video_id, part_index, source, language, subtitle_format, transcript_text,
                 raw_subtitle, artifact_path, digest, utc_now()),
            )
            row = conn.execute(
                'SELECT id FROM part_transcripts WHERE video_id=? AND part_index=? AND content_sha256=?',
                (video_id, part_index, digest),
            ).fetchone()
            return int(row['id'])

    def get_part_transcripts(self, video_id: str) -> dict[int, sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT pt.* FROM part_transcripts pt WHERE pt.video_id=? AND pt.id=(
                   SELECT MAX(p2.id) FROM part_transcripts p2
                   WHERE p2.video_id=pt.video_id AND p2.part_index=pt.part_index)""",
                (video_id,),
            )
            return {int(r['part_index']): r for r in rows}

    def add_segments(self, transcript_id: int, cues: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute('DELETE FROM transcript_segments WHERE transcript_id=?', (transcript_id,))
            conn.executemany(
                """INSERT INTO transcript_segments(transcript_id,segment_index,part_index,start_ms,end_ms,text)
                   VALUES(?,?,?,?,?,?)""",
                [(transcript_id, i, cue['part_index'], cue['start_ms'], cue['end_ms'], cue['text'])
                 for i, cue in enumerate(cues, start=1)],
            )

    def search_segments(self, phrase: str, limit: int = 20) -> list[dict[str, Any]]:
        if len(phrase.strip()) < 3:  # FTS5 trigram needs 3 Unicode characters
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT ts.*, t.video_id FROM transcript_segments_fts
                   JOIN transcript_segments ts ON ts.id=transcript_segments_fts.rowid
                   JOIN transcripts t ON ts.transcript_id=t.id
                   WHERE transcript_segments_fts.text LIKE ? ESCAPE '\\' LIMIT ?""",
                ('%' + phrase.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%', max(1, min(1000, limit))),
            )
            return [dict(r) for r in rows]

    def log_llm_usage(self, video_id: str | None, stage: str, provider: str, model: str,
                      prompt_tokens: int | None, completion_tokens: int | None,
                      estimated_cost_usd: float | None, duration_seconds: float,
                      status: str, error_type: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO llm_usage(video_id,stage,provider,model,prompt_tokens,
                   completion_tokens,estimated_cost_usd,duration_seconds,status,error_type,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (video_id,stage,provider,model,prompt_tokens,completion_tokens,
                 estimated_cost_usd,duration_seconds,status,error_type,utc_now()),
            )

    def estimated_llm_spend(self) -> float:
        with self.connect() as conn:
            return float(conn.execute('SELECT COALESCE(SUM(estimated_cost_usd),0) FROM llm_usage').fetchone()[0])

    def llm_cost_summary(self) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("""SELECT COUNT(*) AS requests,
                COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens),0) AS completion_tokens,
                COALESCE(SUM(estimated_cost_usd),0.0) AS estimated_cost_usd,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed_requests,
                SUM(CASE WHEN estimated_cost_usd IS NULL THEN 1 ELSE 0 END) AS unpriced_requests
                FROM llm_usage""").fetchone()
            return dict(row)
