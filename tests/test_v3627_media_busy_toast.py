"""V3.62.3: a media tap while the previous one renders says why, not nothing."""
from pathlib import Path

SPA = (Path(__file__).resolve().parents[1] / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_busy_tap_shows_a_toast():
    assert SPA.count('if (mediaBusy) { toast(L.media_busy); return; }') == 2
    assert "media_busy: 'Подожди, она ещё занята прошлым фото…'" in SPA
