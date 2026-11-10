from pathlib import Path

from bili_intel.db import Database


def test_db_upsert_and_null_metrics(tmp_path: Path):
    db = Database(tmp_path / "test.sqlite3")
    db.initialize()
    db.upsert_creator("123", "https://space.bilibili.com/123/video")
    db.upsert_video({
        "video_id": "BV1xx411c7mD", "bvid": "BV1xx411c7mD", "creator_mid": "123",
        "title": "Test", "url": "https://www.bilibili.com/video/BV1xx411c7mD/",
        "stats": {"view_count": 100, "like_count": None, "coin_count": None},
    })
    assert db.counts()["videos"] == 1
    with db.connect() as conn:
        row = conn.execute("SELECT view_count, like_count, coin_count FROM video_stats").fetchone()
    assert row["view_count"] == 100
    assert row["like_count"] is None
    assert row["coin_count"] is None
