import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from bili_intel import llm, asr
from bili_intel.db import Database
from bili_intel.runtime import StageLimits


class FakeEncoding:
    def encode(self,x): return list(x)
    def decode(self,ids): return ''.join(ids)


def valid_result():
    return {'title':'ok','executive_summary':'ok','core_thesis':'ok','key_points':[],
            'concepts':[],'arguments_and_evidence':[],'conclusions':[],
            'actionable_takeaways':[],'outline':[],'notable_quotes':[],
            'uncertainty_and_gaps':[],'tags':[]}


def test_token_chunks_preserves_chinese_and_budget():
    text='中文语音测试，很长的句子\n' * 12
    chunks=llm._token_chunks(text,32,FakeEncoding())
    assert ''.join(chunks)==text
    assert all(len(FakeEncoding().encode(c))<=32 for c in chunks)


def test_schema_validation_rejects_missing_fields():
    with pytest.raises(ValueError):
        llm._validate_result('{"title":"incomplete"}')
    assert llm._validate_result(json.dumps(valid_result()))['title']=='ok'
    assert llm.PROMPT_VERSION.startswith('video-analysis-v3:')
    schema=llm.VideoAnalysis.model_json_schema()
    assert schema['additionalProperties'] is False
    assert set(schema['required'])==set(valid_result())


def test_llm_records_usage_and_spend(tmp_path,monkeypatch):
    monkeypatch.setattr(llm,'_encoding',lambda _:FakeEncoding())
    payload=json.dumps(valid_result())
    calls=[]
    class FakeCompletions:
        def create(self,**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason='stop', message=SimpleNamespace(content=payload,refusal=None))],
                usage=SimpleNamespace(prompt_tokens=100,completion_tokens=25))
    client=SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr(llm,'_client',lambda:client)
    db=Database(tmp_path/'db.sqlite3');db.initialize()
    db.upsert_creator('1','https://space.bilibili.com/1')
    db.upsert_video({'video_id':'BV0000000000','creator_mid':'1','url':'https://www.bilibili.com/video/BV0000000000'})
    settings=SimpleNamespace(llm_model='fake',llm_max_input_tokens=6000,
                             llm_max_output_tokens=600,llm_mode='schema',
                             llm_input_usd_per_mtok=1.0,llm_output_usd_per_mtok=2.0,
                             llm_budget_usd=1.0)
    result=llm.analyze_transcript('这是重要观点。',settings,db=db,video_id='BV0000000000',
                                  limits=StageLimits(network=1,asr=1,llm=1,rpm=100,tpm=50000))
    assert result['title']=='ok'
    assert calls[0]['response_format']['type']=='json_schema'
    with db.connect() as conn:
        row=conn.execute('SELECT * FROM llm_usage').fetchone()
    assert row['status']=='success' and row['prompt_tokens']==100
    assert abs(db.estimated_llm_spend()-.00015)<1e-10


def test_asr_model_is_cached(tmp_path,monkeypatch):
    models=[]
    class Model:
        def __init__(self,*args,**kwargs): models.append((args,kwargs))
    import sys
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=Model))
    asr._load_model.cache_clear()
    settings=SimpleNamespace(whisper_model='small',whisper_device='cpu',whisper_compute_type='int8')
    assert asr.get_model(settings) is asr.get_model(settings)
    assert len(models)==1
    asr._load_model.cache_clear()


def test_schema_invalid_response_logs_billed_attempts(tmp_path,monkeypatch):
    monkeypatch.setattr(llm,'_encoding',lambda _:FakeEncoding())
    calls=[]
    good=json.dumps(valid_result())
    class Completions:
        def create(self,**kwargs):
            calls.append(kwargs)
            payload = '{"title":"broken"}' if len(calls)==1 else good
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
                message=SimpleNamespace(content=payload,refusal=None))],
                usage=SimpleNamespace(prompt_tokens=30,completion_tokens=8))
    client=SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(llm,'_client',lambda:client)
    monkeypatch.setattr(llm.time,'sleep',lambda _:None)
    db=Database(tmp_path/'d.sqlite3');db.initialize()
    settings=SimpleNamespace(llm_model='fake',llm_max_input_tokens=6000,
                             llm_max_output_tokens=600,llm_mode='schema',
                             llm_input_usd_per_mtok=1.0,llm_output_usd_per_mtok=2.0,
                             llm_budget_usd=1.0)
    result=llm.analyze_transcript('enough transcript',settings,db=db)
    assert result['title']=='ok'
    with db.connect() as conn:
        rows=conn.execute('SELECT status,estimated_cost_usd FROM llm_usage ORDER BY id').fetchall()
    assert [r['status'] for r in rows]==['failed','success']
    assert all(r['estimated_cost_usd'] is not None for r in rows)
