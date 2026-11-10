import pytest

from bili_intel.urltools import canonical_video_url, extract_mid, extract_video_id


def test_extract_mid():
    assert extract_mid("https://space.bilibili.com/123456/video") == "123456"


def test_extract_bvid():
    assert extract_video_id("https://www.bilibili.com/video/BV1xx411c7mD/?p=2") == "BV1xx411c7mD"


def test_extract_avid():
    assert extract_video_id("https://www.bilibili.com/video/av12345/") == "av12345"


def test_reject_wrong_host():
    with pytest.raises(ValueError):
        extract_mid("https://example.com/123456")


def test_canonical_url():
    assert canonical_video_url("BV1xx411c7mD") == "https://www.bilibili.com/video/BV1xx411c7mD/"
