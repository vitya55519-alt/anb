"""V3.167.28: загруженная картинка-«лицо» доезжает до Spicy на всех дорогах.

Владелец 20.11: «вот пусть фото используется как референс, и рисует спайси а не
гемини, и рисует моих моделей». Три вещи, которые это проверяют:

1. Промпт аватара называет референс по имени («Image 1») — сам движок пишет,
   что безымянные референсы «blend rather than used».
2. Картинка перестаёт стираться сразу после первой попытки: она лежит рядом с
   её аватаром, и повтор через 5/15 минут и «долечивание» рисуют по ней.
3. Это private-файл: витрина, галерея и все будущие кадры знают только
   ``avatar.jpg``, поэтому загруженная картинка наружу не выходит.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from services import photo_service as ps
from services.custom_character_service import (
    build_avatar_prompt, save_custom_character,
)

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
CCS = (ROOT / 'services' / 'custom_character_service.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')

PARAMS = {'name': 'Проверка', 'style': 'style_real', 'age': 'age_confident', 'face': 'face_oval',
          'body': 'body_curvy', 'breast': 'breast_large', 'waist': 'waist_thin', 'hips': 'hips_big',
          'hair': 'hair_brunette', 'eyes': 'eyes_brown'}


class FakeBot:
    def __init__(self, payload: bytes | None = None):
        self.payload = payload
        self.calls: list[str] = []

    async def download(self, file_id):
        self.calls.append(file_id)
        if self.payload is None:
            raise RuntimeError('file gone')

        class _Stream:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

        return _Stream(self.payload)


@pytest.fixture()
def ref_dir(monkeypatch, tmp_path):
    folder = tmp_path / 'custom_references'
    monkeypatch.setattr(ps, '_custom_reference_dir', lambda character_id: folder / character_id)
    return folder


# ── 1. промпт ──────────────────────────────────────────────────────────────

def test_the_prompt_names_the_picture_image_one():
    prompt = build_avatar_prompt(PARAMS, face_swap=True)
    assert 'CRITICAL IDENTITY — Image 1 is her look-alike picture' in prompt
    assert 'Preserve the exact same face' in prompt
    assert 'Do not beautify, slim or retouch the face' in prompt
    anime = dict(PARAMS, style='style_anime')
    assert 'Image 1 is her look-alike picture' in build_avatar_prompt(anime, face_swap=True)


def test_the_figure_still_comes_from_his_settings_not_from_the_picture():
    """Его параметры (грудь/бёдра) обязаны побеждать: картинка даёт только лицо."""
    prompt = build_avatar_prompt(PARAMS, face_swap=True)
    assert 'FINAL BODY LOCK (overrides the reference photo)' in prompt
    assert 'Image 1 supplies the face ONLY' in prompt


def test_no_picture_no_identity_line():
    prompt = build_avatar_prompt(PARAMS)
    assert 'Image 1' not in prompt
    assert 'FINAL BODY LOCK' in prompt


# ── 2. картинка переживает первую попытку ──────────────────────────────────

def test_the_constructor_reads_and_keeps_the_picture():
    body = MAIN[MAIN.index('async def _finish_constructor('):
                MAIN.index("@dp.callback_query(F.data == 'constructor:start')")]
    assert 'face_payload = identity_anchor.read_bytes()' in body
    assert 'await remember_custom_face_reference(row.character_id, face_payload)' in body
    assert '_retry_constructor_avatar(telegram_id, row.character_id, face_payload)' in body
    # and the pending marker is no longer written as if it were a Telegram file
    assert "photo_reference_file_id == 'base64_pending'" in body


def test_the_retry_draws_from_the_picture():
    retry = MAIN[MAIN.index('async def _retry_constructor_avatar('):
                 MAIN.index('async def _constructor_draft_sweep(')]
    assert 'reference = await custom_face_reference(bot, character_id)' in retry
    assert 'build_avatar_prompt(params, face_swap=bool(reference)), reference' in retry


def test_saved_picture_is_used_and_reloaded_once(ref_dir):
    ref_dir.mkdir(parents=True)
    (ref_dir / 'custom_saved').mkdir()
    target = ref_dir / 'custom_saved' / ps.CUSTOM_FACE_FILE
    target.write_bytes(b'PICTURE')
    bot = FakeBot()
    found = asyncio.run(ps.custom_face_reference(bot, 'custom_saved'))
    assert found == target
    assert bot.calls == []          # with the file on disk nothing is fetched


def test_a_bot_upload_comes_back_from_telegram_and_is_cached(ref_dir):
    row = save_custom_character(777000556, display_name='Проверка', params=PARAMS,
                                photo_reference_file_id='tg-picture-id')
    bot = FakeBot(b'PICTURE')
    found = asyncio.run(ps.custom_face_reference(bot, row.character_id))
    assert found and found.read_bytes() == b'PICTURE'
    assert bot.calls == ['tg-picture-id']
    assert asyncio.run(ps.custom_face_reference(bot, row.character_id)) == found
    assert bot.calls == ['tg-picture-id']       # second call reads the disk copy


def test_the_mini_app_marker_names_no_picture(ref_dir):
    """'base64_pending' — то, что приложение писало в это поле раньше."""
    row = save_custom_character(777000557, display_name='Проверка', params=PARAMS,
                                photo_reference_file_id='base64_pending')
    bot = FakeBot(b'PICTURE')
    assert asyncio.run(ps.custom_face_reference(bot, row.character_id)) is None
    assert bot.calls == []


def test_a_character_without_a_picture_stays_text_only(ref_dir):
    row = save_custom_character(777000558, display_name='Проверка', params=PARAMS)
    bot = FakeBot()
    assert asyncio.run(ps.custom_face_reference(bot, row.character_id)) is None
    assert bot.calls == []


# ── 3. приватность ─────────────────────────────────────────────────────────

def test_the_source_picture_is_never_a_public_reference():
    # витрина и галерея знают ровно один файл — её аватар
    assert "base / 'custom_references' / character_id / 'avatar.jpg'" in WEBAPP_SVC
    assert ps.CUSTOM_FACE_FILE not in WEBAPP_SVC
    # и каждый якорь личности в профиле персонажа тоже смотрит на аватар
    profile = PHOTO[PHOTO.index('def _custom_character_profile('):PHOTO.index('def resolve_character(')]
    assert profile.count("'avatar.jpg'") >= 6
    assert ps.CUSTOM_FACE_FILE not in profile


def test_the_avatar_leg_no_longer_sends_a_bare_data_string_first():
    start = PHOTO.index('async def generate_custom_avatar(')
    edit = PHOTO[start:PHOTO.index('\nasync def ', start + 10)]
    assert 'spicy_jobs.upload(' in edit
    assert "prompt, refs, scene='avatar_edit', breaker=False" in edit
    assert '_gemini_edit' not in edit
