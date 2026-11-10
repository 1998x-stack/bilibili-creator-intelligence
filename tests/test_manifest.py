import csv
import json
from pathlib import Path

from bili_intel.manifest import load_manifest


def test_manifest_maps_bilibili_raw_stat_and_preserves_nulls(tmp_path: Path):
    manifest = tmp_path / "videos.csv"
    raw = {"stat": {"view": 123, "like": 8, "coin": 3, "favorite": 4, "share": 5, "danmaku": 6, "reply": 7}}
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["video_url", "title", "view_count", "like_count", "raw_metadata_json"])
        writer.writeheader()
        writer.writerow({
            "video_url": "https://www.bilibili.com/video/BVxxxxxxxxxx/",
            "title": "Demo",
            "view_count": "",
            "like_count": "",
            "raw_metadata_json": json.dumps(raw),
        })
    video = load_manifest(manifest, "123456")[0]
    assert video["stats"]["view_count"] == 123
    assert video["stats"]["coin_count"] == 3
    assert video["stats"]["comment_count"] == 7
