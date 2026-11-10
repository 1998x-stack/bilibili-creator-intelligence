"""Foreground threaded worker pool backed by SQLite queue leases."""
from __future__ import annotations

import json
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread

from .pipeline import process_video
from .queue import WorkQueue
from .runtime import StageLimits


def run_batch(db, rows, settings, args) -> dict[str, int]:
    """Run a bounded set of video tasks; recover/retry work after interruption.

    Each worker owns a fenced lease and refreshes it while processing. Retry
    scheduling is persisted in SQLite and shared by workers.
    """
    if args.limit < 0:
        raise ValueError('--limit must be >= 0')
    rows = rows[:args.limit] if args.limit else rows
    if not rows:
        return {}
    batch_id = uuid.uuid4().hex
    queue = WorkQueue(db)
    for row in rows:
        queue.enqueue(row['video_id'], batch_id=batch_id,
                      max_attempts=getattr(args,'max_attempts',3),
                      retry_failed=getattr(args,'retry_failed',False))
    if getattr(args, 'queue_only', False):
        return queue.summary(batch_id)
    limits = StageLimits(
        network=getattr(args,'network_workers',None) or settings.network_workers,
        asr=getattr(args,'asr_workers',None) or settings.asr_workers,
        llm=getattr(args,'llm_workers',None) or settings.llm_workers,
        rpm=settings.llm_rpm, tpm=settings.llm_tpm,
    )
    worker_count = getattr(args,'workers',None) or settings.workers
    lease_seconds = 900
    start = time.monotonic()
    timeout = getattr(args,'max_wait_seconds',0)

    def run_worker():
        while True:
            if timeout and time.monotonic() - start > timeout:
                return
            item = queue.claim(batch_id=batch_id, lease_seconds=lease_seconds)
            if item is None:
                status = queue.summary(batch_id)
                if not status.get('running') and not status.get('pending'):
                    return
                time.sleep(.2)
                continue
            stop = Event()
            lease_lost = Event()

            def renew():
                while not stop.wait(30):
                    if not queue.renew(item, lease_seconds):
                        lease_lost.set()
                        return

            heartbeat = Thread(target=renew, daemon=True)
            heartbeat.start()
            try:
                row = db.get_videos(video_id=item.video_id)[0]
                process_video(
                    db,row,settings,authorized_content_use=args.authorized_content_use,
                    fetch_metadata=not args.no_metadata,
                    fetch_subtitles=not(args.no_subtitles or args.metadata_only),
                    run_asr=not(args.no_asr or args.metadata_only),
                    run_llm=not(args.no_llm or args.metadata_only),limits=limits,
                )
                if lease_lost.is_set() or not queue.finish(item):
                    print(f'Lost task lease: {item.video_id}', file=sys.stderr)
            except Exception as exc:
                status = queue.fail(item, exc)
                print(f'{item.video_id} attempt {item.attempts}: {type(exc).__name__}: {exc} ({status})', file=sys.stderr)
            finally:
                stop.set()
                heartbeat.join(timeout=2)

    with ThreadPoolExecutor(max_workers=worker_count,thread_name_prefix='bci') as pool:
        futures=[pool.submit(run_worker) for _ in range(worker_count)]
        for future in futures:
            future.result()
    return queue.summary(batch_id)
