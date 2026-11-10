import sys
from types import SimpleNamespace

import pytest

from bili_intel.sources import YtDlpSpaceSource, normalize_playlist_entry


BV1 = 'BV1xx411c7mD'
BV2 = 'BV1aa411c7mD'


class FakeYDL:
    payload = {}
    options = {}

    def __init__(self, options):
        type(self).options = options

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def extract_info(self, url, download=False):
        assert url == 'https://space.bilibili.com/123/video'
        assert download is False
        return type(self).payload


@pytest.fixture
def fake_yt_dlp(monkeypatch):
    monkeypatch.setitem(sys.modules, 'yt_dlp', SimpleNamespace(YoutubeDL=FakeYDL))
    return FakeYDL


def test_normalizes_verified_bvid_and_preserves_missing_stats():
    got = normalize_playlist_entry({'id': BV1, 'title': 'Hello', 'view_count': 0}, '123')
    assert got['video_id'] == BV1
    assert got['stats']['view_count'] == 0
    assert got['stats']['coin_count'] is None
    assert got['url'] == f'https://www.bilibili.com/video/{BV1}/'


def test_rejects_different_creator():
    with pytest.raises(ValueError, match='another creator'):
        normalize_playlist_entry({'id': BV1, 'uploader_id': '777'}, '123')


def test_ytdlp_space_discovers_unique_videos(tmp_path, fake_yt_dlp):
    fake_yt_dlp.payload = {
        '_type': 'playlist',
        'id': '123',
        'playlist_count': 2,
        'entries': [{'id': BV1, 'title': 'A'}, {'id': BV2, 'title': 'B'}, {'id': BV1}],
    }
    settings = SimpleNamespace(artifacts_dir=tmp_path, cookies_file=None)
    source = YtDlpSpaceSource('https://space.bilibili.com/123/video', settings)
    videos = source.list_videos('123')
    assert len(videos) == 2
    assert source.last_report['found'] == 2
    assert source.last_report['complete'] is None
    assert fake_yt_dlp.options['extract_flat'] == 'in_playlist'
    assert fake_yt_dlp.options['skip_download'] is True
    assert fake_yt_dlp.options['sleep_interval_requests'] == 1.0


def test_discovery_cap_explicitly_marks_incomplete(tmp_path, fake_yt_dlp):
    fake_yt_dlp.payload = {'_type': 'playlist', 'entries': [{'id': BV1}]}
    source = YtDlpSpaceSource('https://space.bilibili.com/123',
                             SimpleNamespace(artifacts_dir=tmp_path, cookies_file=None),
                             max_videos=1)
    assert len(source.list_videos('123')) == 1
    assert source.last_report['complete'] is False
    assert fake_yt_dlp.options['playlistend'] == 1


def test_unknown_entry_fails_loudly(tmp_path, fake_yt_dlp):
    fake_yt_dlp.payload = {'_type': 'playlist', 'entries': [{'id': 'invalid'}]}
    source = YtDlpSpaceSource('https://space.bilibili.com/123',
                             SimpleNamespace(artifacts_dir=tmp_path, cookies_file=None))
    with pytest.raises(RuntimeError, match='not video IDs'):
        source.list_videos('123')


def test_empty_entry_fails_loudly(tmp_path, fake_yt_dlp):
    fake_yt_dlp.payload = {'_type': 'playlist', 'entries': [None]}
    source = YtDlpSpaceSource('https://space.bilibili.com/123',
                             SimpleNamespace(artifacts_dir=tmp_path, cookies_file=None))
    with pytest.raises(RuntimeError, match='missing entry'):
        source.list_videos('123')


def test_creator_url_mid_mismatch(tmp_path, fake_yt_dlp):
    source = YtDlpSpaceSource('https://space.bilibili.com/999',
                             SimpleNamespace(artifacts_dir=tmp_path, cookies_file=None))
    with pytest.raises(ValueError, match='MID'):
        source.list_videos('123')
