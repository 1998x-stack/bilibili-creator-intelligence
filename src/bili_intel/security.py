"""Consistent safe allowlists for persisted remote/provider metadata."""
from __future__ import annotations

SAFE_FIELDS = {
    'id','display_id','bvid','aid','cid','title','description','uploader',
    'uploader_id','channel','channel_id','timestamp','upload_date','release_date',
    'duration','categories','tags','category','view_count','like_count',
    'coin_count','favorite_count','share_count','danmaku_count','comment_count',
}
SAFE_STAT_FIELDS = {'view','like','coin','favorite','share','danmaku','reply'}


def sanitize_metadata(raw: dict | None) -> dict:
    """Never persist arbitrary signed URLs, token/cookie headers or nested objects."""
    if not isinstance(raw, dict):
        return {}
    result = {}
    for key,value in raw.items():
        if key in SAFE_FIELDS and isinstance(value,(str,int,float,bool,type(None))):
            result[key] = value
        elif key in {'tags','categories'} and isinstance(value,list):
            result[key] = [x for x in value if isinstance(x,(str,int,float))][:500]
        elif key == 'stat' and isinstance(value,dict):
            result['stat'] = {k:v for k,v in value.items()
                              if k in SAFE_STAT_FIELDS and isinstance(v,(int,float,type(None)))}
    return result
