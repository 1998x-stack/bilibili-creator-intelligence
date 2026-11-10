from pathlib import Path
from types import SimpleNamespace

import pytest

from bili_intel.db import Database
from bili_intel.parts import parse_part_inventory, part_url
from bili_intel import pipeline
from bili_intel.ytdlp_adapter import SubtitleFile

BV = 'BV1xx411c7mD'
SRT_1 = '1\n00:00:01,000 --> 00:00:02,000\n你好世界\n'
SRT_2 = '1\n00:00:01,000 --> 00:00:02,000\n后半部分\n'


def inventory():
    return {'_type':'playlist', 'playlist_count':2, 'entries':[
        {'url':part_url(BV,1),'title':'上半集','cid':123},
        {'url':part_url(BV,2),'title':'下半集','cid':456},
    ]}


def make_db(tmp_path):
    db = Database(tmp_path/'db.sqlite3')
    db.initialize()
    db.upsert_creator('123', 'https://space.bilibili.com/123/video')
    db.upsert_video({'video_id':BV,'creator_mid':'123','url':part_url(BV,1),'title':'test'})
    return db


def test_two_part_inventory_and_incomplete_rejection():
    parts = parse_part_inventory(inventory(),BV)
    assert [p['cid'] for p in parts]==[123,456]
    assert [p['url'] for p in parts]==[part_url(BV,1),part_url(BV,2)]
    broken=inventory()
    broken['entries'].pop()
    with pytest.raises(ValueError,match='Partial'):
        parse_part_inventory(broken,BV)
    broken=inventory()
    broken['entries'][1]['url']=part_url(BV,3)
    with pytest.raises(ValueError,match='order'):
        parse_part_inventory(broken,BV)


def test_two_part_pipeline_with_asr_fallback_and_fts(tmp_path,monkeypatch):
    db=make_db(tmp_path)
    settings=SimpleNamespace(artifacts_dir=tmp_path/'artifacts',llm_model='mock')
    monkeypatch.setattr(pipeline,'discover_parts',lambda *a:parse_part_inventory(inventory(),BV))

    def download_sub(url,settings,dest):
        dest.mkdir(parents=True,exist_ok=True)
        if '?p=2' in url:
            return []
        file=dest/'a.zh-CN.srt'
        file.write_text(SRT_1,encoding='utf8')
        return [SubtitleFile(file,'zh-CN','subtitles')]

    monkeypatch.setattr(pipeline,'download_subtitles',download_sub)
    monkeypatch.setattr(pipeline,'download_audio',lambda *a:tmp_path/'two.mp3')
    monkeypatch.setattr(pipeline,'transcribe_audio',lambda *a:(SRT_2,'zh'))
    pipeline.process_video(db,db.get_videos(video_id=BV)[0],settings,
                           authorized_content_use=True,fetch_metadata=False,run_llm=False)
    assert db.counts()['video_parts']==2
    assert db.counts()['part_transcripts']==2
    assert db.counts()['transcript_segments']==2
    assert 'P1' in db.latest_transcript(BV)['transcript_text']
    assert 'P2' in db.latest_transcript(BV)['transcript_text']
    assert db.search_segments('你好世界')[0]['part_index']==1
    assert db.search_segments('后半部分')[0]['part_index']==2
    # Cache prevents a repeat ASR or download.
    monkeypatch.setattr(pipeline,'download_audio',lambda *a:pytest.fail('repeat download'))
    pipeline.process_video(db,db.get_videos(video_id=BV)[0],settings,
                           authorized_content_use=True,fetch_metadata=False,run_llm=False)
    assert db.counts()['part_transcripts']==2


def test_no_partial_assembly_on_missing_part(tmp_path,monkeypatch):
    db=make_db(tmp_path)
    settings=SimpleNamespace(artifacts_dir=tmp_path/'artifacts',llm_model='mock')
    monkeypatch.setattr(pipeline,'discover_parts',lambda *a:parse_part_inventory(inventory(),BV))

    def sub(url,settings,dest):
        if '?p=2' in url:
            return []
        dest.mkdir(parents=True,exist_ok=True)
        file=dest/'a.zh-CN.srt';file.write_text(SRT_1,encoding='utf8')
        return [file]
    monkeypatch.setattr(pipeline,'download_subtitles',sub)
    with pytest.raises(RuntimeError,match='Part 2'):
        pipeline.process_video(db,db.get_videos(video_id=BV)[0],settings,
                               authorized_content_use=True,fetch_metadata=False,run_asr=False,run_llm=False)
    assert db.latest_transcript(BV) is None
    assert db.counts()['part_transcripts']==1


def test_export_requires_analysis_for_same_transcript(tmp_path):
    db=make_db(tmp_path)
    a=db.add_transcript(BV,'test','zh','one',SRT_1,None,'old')
    db.add_analysis(BV,a,'old','openai','model','prompt',{'title':'old'},'old')
    db.add_transcript(BV,'test','zh','two',SRT_2,None,'new')
    out=tmp_path/'export.jsonl'
    db.export_jsonl('123',out)
    import json
    record=json.loads(out.read_text().splitlines()[0])
    assert record['transcript']['content_sha256']=='new'
    assert record['analysis'] is None
