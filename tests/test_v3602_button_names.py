"""V3.60.2: every «Наедине» button reads clean — one emoji, plain Russian."""
import re

from services import private_photo_service as p


def _labels():
    for c in p.PRIVATE_PHOTO_CATEGORIES.values():
        yield c['name_ru']
        for t in c.get('types', []):
            yield t['name_ru']
    for l in p.LOCATIONS:
        yield l['name_ru']
    for m in p.MOODS:
        yield m['name_ru']


def test_every_label_starts_with_an_emoji_and_has_no_plus_sign():
    for label in _labels():
        assert not re.match(r'^[\w\s]', label[0]), label
        assert '+' not in label and 'нюдо' not in label, label
