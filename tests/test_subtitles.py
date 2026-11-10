from bili_intel.subtitles import cues_to_text, parse_srt, parse_vtt, seconds_to_srt_time


SRT = """1
00:00:01,000 --> 00:00:02,500
你好，世界。

2
00:00:03,000 --> 00:00:04,000
第二句
"""


def test_parse_srt_and_timestamp_text():
    cues = parse_srt(SRT)
    assert len(cues) == 2
    assert cues[0]["text"] == "你好，世界。"
    assert "[00:00:01.000 - 00:00:02.500] 你好，世界。" in cues_to_text(cues)


def test_seconds_to_srt_time():
    assert seconds_to_srt_time(61.25) == "00:01:01,250"


VTT = """WEBVTT

00:01.000 --> 00:02.500
你好，VTT。
"""


def test_parse_vtt_without_hour_component():
    cues = parse_vtt(VTT)
    assert len(cues) == 1
    assert cues[0]["start"] == "00:00:01.000"
    assert cues[0]["text"] == "你好，VTT。"
