import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bili_intel import cli, pipeline
from bili_intel.db import Database
from bili_intel.llm import _chunks, _validate_result
from bili_intel.ytdlp_adapter import info_to_video_update

BV = 'BV1xx411c7mD'
URL = f'https://www.bilibili.com/video/{BV}/'
SPACE = 'https://space.bilibili.com/123/video'
SRT = '''1
00:00:01,000 --> 00:00:02,500
你好世界。

2
00:00:03,000 --> 00:00:04,000
这是测试。
'''


def make_db(tmp_path):
    db = Database(tmp_path / 'state.db')
    db.initialize()
    db.upsert_creator('123', SPACE)
    db.upsert_video({'video_id': BV, 'creator_mid': '123', 'url': URL, 'title': 'A'})
    return db


def settings(tmp_path):
    return SimpleNamespace(artifacts_dir=tmp_path / 'artifacts', llm_model='fake-test')


def test_import_is_offline_and_audited(tmp_path, monkeypatch):
    monkeypatch.setenv('BCI_DB_PATH', str(tmp_path / 'state.db'))
    monkeypatch.setenv('BCI_ARTIFACTS_DIR', str(tmp_path / 'artifacts'))
    csv_path = tmp_path / 'manifest.csv'
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['video_url', 'title', 'like_count'])
        w.writeheader()
        w.writerow({'video_url': URL, 'title': 'Demo', 'like_count': '0'})
    assert cli.main(['ingest', '--space-url', SPACE, '--manifest', str(csv_path)]) == 0
    db = Database(tmp_path / 'state.db')
    assert db.counts()['videos'] == 1
    with db.connect() as c:
        run = c.execute('SELECT * FROM discovery_runs').fetchone()
        assert run['status'] == 'success'
        stat = c.execute('SELECT like_count, coin_count FROM video_stats').fetchone()
        assert stat['like_count'] == 0
        assert stat['coin_count'] is None
    target = tmp_path / 'exports' / 'out.jsonl'
    assert cli.main(['export', '--mid', '123', '--output', str(target)]) == 0
    records = [json.loads(line) for line in target.read_text().splitlines()]
    assert len(records) == 1 and records[0]['stats']['like_count'] == 0


def test_remote_discovery_requires_permission(tmp_path, monkeypatch):
    monkeypatch.setenv('BCI_DB_PATH', str(tmp_path / 'state.db'))
    assert cli.main(['discover', '--space-url', SPACE, '--source', 'yt-dlp']) == 1


def test_metadata_update_does_not_erase_title(tmp_path):
    db = make_db(tmp_path)
    db.upsert_video({'video_id': BV, 'creator_mid': '123', 'url': URL, 'title': '',
                     'stats': {'view_count': 3}})
    row = db.get_videos(video_id=BV)[0]
    assert row['title'] == 'A'
    with db.connect() as conn:
        assert conn.execute('SELECT view_count FROM video_stats').fetchone()['view_count'] == 3


def test_metadata_safe_fields_do_not_keep_signed_stream_urls():
    update = info_to_video_update({
        'id': BV, 'title': 'Safe', 'view_count': 2,
        'formats': [{'url': 'https://cdn.invalid/?token=SECRET'}],
        'http_headers': {'Cookie': 'SECRET'},
        'cookies': 'SECRET',
        'thumbnail': 'https://cdn.invalid/img.jpg',
    }, '123', URL)
    assert update['stats']['view_count'] == 2
    assert 'SECRET' not in json.dumps(update)


def test_existing_subtitle_skips_asr_and_llm_cache(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    def subtitles(url, settings, directory):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{BV}.ai-zh.srt'
        path.write_text(SRT, encoding='utf-8')
        return [path]
    monkeypatch.setattr(pipeline, 'download_subtitles', subtitles)
    monkeypatch.setattr(pipeline, 'download_audio', lambda *args: pytest.fail('unexpected ASR'))
    calls = []
    def analyze(text, settings):
        calls.append(text)
        return {'title': 'A', 'executive_summary': 'Summary', 'key_points': [], 'tags': []}
    monkeypatch.setattr(pipeline, 'analyze_transcript', analyze)
    for _ in range(2):
        pipeline.process_video(db, db.get_videos(video_id=BV)[0], settings(tmp_path),
                               authorized_content_use=True, run_asr=True)
    assert len(calls) == 1
    assert db.counts()['transcripts'] == 1
    assert db.counts()['analyses'] == 1
    assert (tmp_path / 'artifacts' / BV / 'analysis' / 'analysis.md').exists()


def test_asr_fallback_when_no_subtitles(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    monkeypatch.setattr(pipeline, 'download_subtitles', lambda *args: [])
    monkeypatch.setattr(pipeline, 'download_audio', lambda *args: Path('audio.mp3'))
    monkeypatch.setattr(pipeline, 'transcribe_audio', lambda *args: (SRT, 'zh'))
    pipeline.process_video(db, db.get_videos(video_id=BV)[0], settings(tmp_path),
                           authorized_content_use=True, run_llm=False)
    assert db.latest_transcript(BV)['source'] == 'faster_whisper'
    assert db.latest_transcript(BV)['language'] == 'zh'


def test_access_guard_precedes_network(tmp_path, monkeypatch):
    db = make_db(tmp_path)
    monkeypatch.setattr(pipeline, 'download_subtitles', lambda *args: pytest.fail('network'))
    with pytest.raises(PermissionError):
        pipeline.process_video(db, db.get_videos(video_id=BV)[0], settings(tmp_path),
                               authorized_content_use=False)


def test_llm_chunker_bounds_single_long_line():
    chunks = _chunks('A'*2011, 100)
    assert ''.join(chunks) == 'A'*2011
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_llm_parser_rejects_bad_shape():
    with pytest.raises(ValueError, match='JSON object'):
        _validate_result('[]')
    with pytest.raises(ValueError, match='must be a list'):
        _validate_result('{"tags":"bad"}')


def test_run_processes_only_this_discovery_not_historical_rows(tmp_path, monkeypatch):
    monkeypatch.setenv('BCI_DB_PATH', str(tmp_path / 'state.db'))
    monkeypatch.setenv('BCI_ARTIFACTS_DIR', str(tmp_path / 'artifacts'))
    db = make_db(tmp_path)
    second = 'BV1aa411c7mD'
    csv_path = tmp_path / 'one.csv'
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['video_url'])
        writer.writeheader()
        writer.writerow({'video_url': f'https://www.bilibili.com/video/{second}/'})
    processed = []
    monkeypatch.setattr(cli, 'process_video', lambda db, video, settings, **kwargs: processed.append(video['video_id']))
    assert cli.main(['run', '--space-url', SPACE, '--manifest', str(csv_path),
                     '--no-metadata', '--no-subtitles', '--no-asr', '--no-llm']) == 0
    assert processed == [second]
    assert db.counts()['videos'] == 2
