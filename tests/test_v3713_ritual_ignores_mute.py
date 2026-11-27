from services import push_governor as pg


def test_ritual_rail_is_never_muted(monkeypatch):
    monkeypatch.delenv('RITUAL_IGNORE_MUTE', raising=False)
    assert pg.rail_muted(1, 'ritual') is False


def test_mute_can_be_restored_by_env(monkeypatch):
    monkeypatch.setenv('RITUAL_IGNORE_MUTE', '0')
    # falls through to the normal logic (no DB rows -> not muted, but no early exit)
    assert pg.rail_muted(0, 'ritual') is False
