from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from threading import Barrier, Lock
import time

from bili_intel.db import Database
from bili_intel.queue import WorkQueue
from bili_intel import scheduler


def db_one(tmp_path,n=1):
    db=Database(tmp_path/'db.sqlite3')
    db.initialize()
    db.upsert_creator('1','https://space.bilibili.com/1')
    for i in range(n):
        db.upsert_video({'video_id':f'BV{i:010d}','creator_mid':'1','url':f'https://www.bilibili.com/video/BV{i:010d}'})
    return db


def test_atomic_queue_claim_lease_retry_and_fencing(tmp_path,monkeypatch):
    db=db_one(tmp_path,3)
    queue=WorkQueue(db)
    for row in db.get_videos():
        queue.enqueue(row['video_id'],batch_id='a',max_attempts=2)
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks=list(pool.map(lambda _: queue.claim(batch_id='a',lease_seconds=20),range(3)))
    assert len({task.video_id for task in tasks})==3
    assert queue.claim(batch_id='a') is None
    assert queue.renew(tasks[0],30)
    assert queue.finish(tasks[0])
    assert not queue.finish(tasks[0])
    assert queue.fail(tasks[1],'network error',backoff_base=0)=='pending'
    nxt=queue.claim(batch_id='a')
    assert nxt and nxt.id==tasks[1].id and nxt.attempts==2
    assert not queue.finish(tasks[1])
    assert queue.fail(nxt,'error again',backoff_base=0)=='failed'
    assert queue.finish(tasks[2])
    assert queue.summary('a')=={'completed':2,'failed':1}


def test_concurrent_scheduler_completion(tmp_path,monkeypatch):
    db=db_one(tmp_path,4)
    settings=SimpleNamespace(workers=3,network_workers=1,asr_workers=1,
                             llm_workers=2,llm_rpm=30,llm_tpm=50000)
    active={'count':0,'high':0}
    lock=Lock()

    def mock_process(db,row,settings,**kwargs):
        with lock:
            active['count']+=1
            active['high']=max(active['count'],active['high'])
        time.sleep(.025)
        with lock:
            active['count']-=1

    monkeypatch.setattr(scheduler,'process_video',mock_process)
    args=SimpleNamespace(limit=0,workers=3,network_workers=1,asr_workers=1,
                         llm_workers=2,max_attempts=2,max_wait_seconds=2,
                         queue_only=False,authorized_content_use=True,no_metadata=False,
                         no_subtitles=False,metadata_only=False,no_asr=False,no_llm=False)
    status=scheduler.run_batch(db,db.get_videos(),settings,args)
    assert status=={'completed':4}
    assert active['high']>=2


def test_failed_queue_requires_explicit_retry(tmp_path):
    db=db_one(tmp_path)
    video_id=db.get_videos()[0]['video_id']
    q=WorkQueue(db)
    q.enqueue(video_id,max_attempts=1,batch_id='a')
    one=q.claim(batch_id='a')
    assert q.fail(one,'permanent')=='failed'
    q.enqueue(video_id,batch_id='b')
    assert q.summary('b')=={'failed':1}
    assert q.claim(batch_id='b') is None
    q.enqueue(video_id,batch_id='b',retry_failed=True,max_attempts=1)
    assert q.claim(batch_id='b') is not None


def test_queue_only_persists_without_running(tmp_path,monkeypatch):
    db=db_one(tmp_path)
    settings=SimpleNamespace(workers=2,network_workers=1,asr_workers=1,
                             llm_workers=2,llm_rpm=30,llm_tpm=50000)
    args=SimpleNamespace(limit=0,max_attempts=3,queue_only=True,retry_failed=False)
    monkeypatch.setattr(scheduler,'process_video',lambda *a,**k:__import__('pytest').fail('Should only queue'))
    assert scheduler.run_batch(db,db.get_videos(),settings,args)=={'pending':1}
