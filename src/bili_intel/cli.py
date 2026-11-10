"""Command-line entrypoint. No remote operations happen without explicit opt-in."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings
from .db import Database
from .pipeline import process_video
from .scheduler import run_batch
from .sources import ManifestSource, YtDlpSpaceSource
from .urltools import extract_mid


def _source_options(p: argparse.ArgumentParser) -> None:
    p.add_argument('--space-url', required=True, help='https://space.bilibili.com/MID/video')
    p.add_argument('--source', choices=('auto', 'manifest', 'yt-dlp'), default='auto')
    p.add_argument('--manifest', type=Path, help='Authorized CSV video list; offline discovery')
    p.add_argument('--max-videos', type=int, default=0, help='Discovery cap (0=all accessible videos)')
    p.add_argument('--authorized-content-use', action='store_true', help='Confirm permissions and platform terms for remote access')


def _process_options(p: argparse.ArgumentParser) -> None:
    p.add_argument('--no-metadata', action='store_true')
    p.add_argument('--no-subtitles', action='store_true')
    p.add_argument('--no-asr', action='store_true')
    p.add_argument('--no-llm', action='store_true')
    p.add_argument('--metadata-only', action='store_true', help='Disable subtitle, ASR and LLM stages')
    p.add_argument('--limit', type=int, default=0, help='Maximum existing videos to process; 0=all')
    p.add_argument('--workers', type=int, default=None, help='Video worker count (default from .env)')
    p.add_argument('--network-workers', type=int, default=None, help='Shared concurrent downloads')
    p.add_argument('--asr-workers', type=int, default=None, help='Concurrent model calls')
    p.add_argument('--llm-workers', type=int, default=None, help='Concurrent LLM requests')
    p.add_argument('--max-attempts', type=int, default=3, help='Durable per-video attempts')
    p.add_argument('--max-wait-seconds', type=float, default=0, help='0=run until batch terminal')
    p.add_argument('--retry-failed', action='store_true', help='Explicitly requeue exhausted tasks')
    p.add_argument('--queue-only', action='store_true', help='Persist tasks without executing them')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='bci', description='Local-first Bilibili creator intelligence')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init-db')
    ingest = sub.add_parser('ingest', help='Offline import of an authorized video CSV manifest')
    ingest.add_argument('--space-url', required=True)
    ingest.add_argument('--manifest', required=True, type=Path)

    discover = sub.add_parser('discover', help='Discover a creator and store video metadata in SQLite')
    _source_options(discover)
    run = sub.add_parser('run', help='Discover and process videos end to end')
    _source_options(run)
    _process_options(run)
    process = sub.add_parser('process', help='Process already discovered video rows')
    process.add_argument('--mid', required=True)
    process.add_argument('--authorized-content-use', action='store_true')
    _process_options(process)
    export = sub.add_parser('export', help='Export a creator summary as JSONL from SQLite')
    export.add_argument('--mid', required=True)
    export.add_argument('--output', required=True, type=Path)
    sub.add_parser('stats')
    sub.add_parser('queue-status', help='Print durable task status counts')
    sub.add_parser('costs', help='Print LLM API token usage and estimated costs')
    search = sub.add_parser('search', help='Search transcript segment text (FTS5 trigram)')
    search.add_argument('phrase')
    search.add_argument('--limit', type=int, default=20)
    return parser


def _discover(db: Database, args, settings: Settings) -> tuple[str, list[str]]:
    mid = extract_mid(args.space_url)
    source_kind = ('manifest' if args.manifest else 'yt-dlp') if args.source == 'auto' else args.source
    if source_kind == 'manifest':
        if not args.manifest:
            raise ValueError('--manifest is required when --source manifest')
        source = ManifestSource(args.manifest)
    else:
        if args.manifest:
            raise ValueError('Use either --manifest or --source yt-dlp, not both')
        if not args.authorized_content_use:
            raise PermissionError('Remote discovery requires --authorized-content-use and actual permission')
        source = YtDlpSpaceSource(args.space_url, settings, max_videos=args.max_videos)
    db.upsert_creator(mid, args.space_url)
    run_id = db.start_discovery(mid, source_kind)
    try:
        videos = source.list_videos(mid)
        if not videos:
            raise ValueError('Source returned an empty video list; no changes to existing videos')
        for video in videos:
            db.upsert_video(video)
        db.finish_discovery(run_id, 'success', len(videos), source.last_report)
        print(f'Imported {len(videos)} unique videos for MID {mid}; discovery={source_kind}')
        print('Coverage:', json.dumps(source.last_report, ensure_ascii=False))
    except Exception as exc:
        db.finish_discovery(run_id, 'failed', 0, {'error': type(exc).__name__, 'detail': str(exc)})
        raise
    return mid, [video['video_id'] for video in videos]


def _process_rows(db: Database, rows, settings, args) -> None:
    for name in ('workers','network_workers','asr_workers','llm_workers'):
        value = getattr(args,name,None)
        if value is not None and value < 1:
            raise ValueError(f'--{name.replace("_","-")} must be positive')
    if args.max_attempts < 1:
        raise ValueError('--max-attempts must be positive')
    if args.max_wait_seconds < 0:
        raise ValueError('--max-wait-seconds must be non-negative')
    status = run_batch(db, rows, settings, args)
    print('Queue result:', json.dumps(status,ensure_ascii=False))
    if not args.queue_only and (status.get('failed') or status.get('pending') or status.get('running')):
        raise RuntimeError(f'Processing incomplete: {status}; resume with bci process')


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.from_env()
    db = Database(settings.db_path)
    db.initialize()
    try:
        if args.command == 'init-db':
            print(f'Initialized: {settings.db_path}')
        elif args.command == 'ingest':
            args.source = 'manifest'
            args.max_videos = 0
            args.authorized_content_use = False
            _discover(db, args, settings)
        elif args.command == 'discover':
            _discover(db, args, settings)
        elif args.command == 'run':
            mid, discovered_ids = _discover(db, args, settings)
            # Only process the rows discovered *this run*, not all historical creator videos.
            # In particular, --max-videos must bound downstream ASR and LLM billing.
            rows = [db.get_videos(video_id=video_id)[0] for video_id in discovered_ids]
            _process_rows(db, rows, settings, args)
            print(json.dumps(db.counts(), ensure_ascii=False))
        elif args.command == 'process':
            if not args.mid.isdigit():
                raise ValueError('--mid must be numeric')
            _process_rows(db, db.get_videos(creator_mid=args.mid), settings, args)
        elif args.command == 'export':
            count = db.export_jsonl(args.mid, args.output)
            print(f'Exported {count} videos to {args.output}')
        elif args.command == 'stats':
            print(json.dumps(db.counts(), ensure_ascii=False, indent=2))
        elif args.command == 'queue-status':
            from .queue import WorkQueue
            print(json.dumps(WorkQueue(db).summary(), ensure_ascii=False, indent=2))
        elif args.command == 'costs':
            print(json.dumps(db.llm_cost_summary(), ensure_ascii=False, indent=2))
        elif args.command == 'search':
            print(json.dumps(db.search_segments(args.phrase,args.limit),ensure_ascii=False,indent=2))
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
