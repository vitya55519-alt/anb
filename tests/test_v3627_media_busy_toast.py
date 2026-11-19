"""V3.62.3: a media tap while the previous one renders says why, not nothing."""
from pathlib import Path

SPA = (Path(__file__).resolve().parents[1] / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_busy_tap_shows_a_toast():
    # V3.165.0 (#104): «Серия кадров» is a third media tap and guards the same way.
    # V3.167.27: the «✨ Фантазия» panel is the fourth media tap, same guard.
    assert SPA.count('if (mediaBusy) { toast(L.media_busy); return; }') == 4
    assert "media_busy: 'Подожди, она ещё занята прошлым фото…'" in SPA
