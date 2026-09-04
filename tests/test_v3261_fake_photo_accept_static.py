"""V3.26.1 static pins: fake-photo interception and relaxed accept regex.

Field report: Anna offered a photo, the user answered «Давай буду рад )», the
anchored _PHOTO_ACCEPT ($-bound, single word) did not match, the chat model
role-played sending a photo as «[фото: ...]» and that raw text reached the
user. Fixes: accept regex is now prefix+word-boundary (with a «нет» guard at
the call site), bracketed fake photos are stripped from every reply and a
real photo flow is triggered instead, and the system prompt forbids the
model from ever writing bracketed photo descriptions.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAR = (ROOT / 'services' / 'character_service.py').read_text(encoding='utf-8')


def _compiled(name: str):
    """Extract a module-level re.compile(<string literal>) from main.py.

    No eval: only the constant pattern argument is read from the AST and
    recompiled here with re.I (the same flag main.py passes).
    """
    tree = ast.parse(MAIN)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            getattr(t, 'id', '') == name for t in node.targets
        ):
            call = node.value
            assert isinstance(call, ast.Call) and call.args, f'{name} must be a compile call'
            pattern = call.args[0]
            assert isinstance(pattern, ast.Constant) and isinstance(pattern.value, str)
            return re.compile(pattern.value, re.I)
    raise AssertionError(f'{name} not found in main.py')


def test_version_bumped():
    assert VERSION in ('3.26.1', '3.30.0', '3.30.1', '3.30.2', '3.30.3', '3.30.4')


def test_accept_regex_matches_real_acceptances():
    accept = _compiled('_PHOTO_ACCEPT')
    # The exact message from the field report must count as acceptance now.
    assert accept.match('давай буду рад )')
    assert accept.match('да')
    assert accept.match('давай')
    assert accept.match('скинь')
    assert accept.match('yes please')
    # Refusals and unrelated text must not match.
    assert not accept.match('нет')
    assert not accept.match('спокойной ночи')
    assert not accept.match('давай потом как-нибудь')


def test_accept_call_site_has_net_guard():
    # «да нет» / «давай не надо» must never trigger the photo flow.
    assert "'нет' not in low" in MAIN
    assert "offer_active and 'нет' not in low and _PHOTO_ACCEPT.match(low)" in MAIN


def test_fake_photo_blocks_stripped_and_delivered():
    fake = _compiled('_FAKE_PHOTO_BLOCK')
    sample = 'держи 😊\n[фото: Anna дома вечером — чёрный топ, мягкие косы]\nвот такая я сейчас'
    cleaned, hit = fake.subn('', sample)
    assert hit == 1 and '[фото' not in cleaned
    assert fake.search('[photo: evening selfie]')
    # Both reply paths (text + voice) sanitize and trigger the real flow.
    assert MAIN.count('_strip_fake_photo(answer)') >= 2
    assert MAIN.count('asyncio.create_task(_deliver_intercepted_photo(message))') >= 2
    assert 'async def _deliver_intercepted_photo(message: types.Message) -> None:' in MAIN
    assert 'async def _photo_accept_flow(chat_id: int, telegram_id: int, expr_key: str | None = None) -> None:' in MAIN


def test_system_prompt_forbids_bracketed_photos():
    assert 'ты никогда не отправляешь фото сама' in CHAR
    assert '[фото: ...]' in CHAR and '[photo: ...]' in CHAR
