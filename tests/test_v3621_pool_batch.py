from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')


def test_pool_upload_accepts_a_pack():
    upload = SRC[SRC.index('async def admin_prophoto_upload('):SRC.index("@dp.callback_query(F.data == 'admin:prophoto:done')")]
    assert 'PROPHOTO_WAIT.pop' not in upload  # the wait stays open for an album
    assert "callback_data='admin:prophoto:done'" in SRC
    assert 'отправь альбомом' in SRC
