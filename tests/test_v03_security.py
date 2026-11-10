from bili_intel.security import sanitize_metadata
from bili_intel.db import Database


def test_metadata_secret_filtering(tmp_path):
    raw={'title':'Allowed','http_headers':{'Cookie':'SECRET'},
         'formats':[{'url':'https://private/?signature=SECRET'}],
         'authorization':'SECRET','token':'SECRET',
         'stat':{'like':11,'csrf':'SECRET'},
         'data':{'secret':'SECRET'}}
    safe=sanitize_metadata(raw)
    assert safe=={'title':'Allowed','stat':{'like':11}}
    db=Database(tmp_path/'db.sqlite3');db.initialize()
    db.upsert_creator('1','https://space.bilibili.com/1',raw)
    db.upsert_video({'video_id':'BV0000000000','creator_mid':'1','title':'Allowed',
                     'url':'https://www.bilibili.com/video/BV0000000000','raw_metadata':raw})
    with db.connect() as conn:
        r=conn.execute('SELECT raw_metadata_json FROM videos').fetchone()
        c=conn.execute('SELECT raw_metadata_json FROM creators').fetchone()
    assert 'SECRET' not in r['raw_metadata_json']+c['raw_metadata_json']
