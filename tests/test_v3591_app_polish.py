"""V3.59.1: tasks are checked against today's chat, the apartment explains
itself, the app paints a splash instead of a blank screen, photos can be saved."""
import os
from pathlib import Path

os.environ.setdefault("TELEGRAM_TOKEN", "123456:test-fake-token-for-static-tests-only")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-for-static-tests-only")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from sqlalchemy import delete, select  # noqa: E402
from models.waifu_models import Base  # noqa: E402
from services.db import engine, SessionLocal  # noqa: E402

Base.metadata.create_all(engine)

from models.app_models import Message, ProductEvent, User  # noqa: E402
from services import couple_service  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
TID = 995911


def _setup():
    with SessionLocal() as s:
        s.add(User(telegram_id=str(TID)))
        s.commit()
        return s.scalar(select(User.id).where(User.telegram_id == str(TID)))


def _say(uid, text):
    with SessionLocal() as s:
        s.add(Message(user_id=uid, character_id='anna_01', role='user', content=text))
        s.commit()


def test_quests_need_the_real_action():
    uid = _setup()
    try:
        assert not couple_service.quest_done_today(TID, 'compliment')
        _say(uid, 'ты сегодня такая красивая')
        assert couple_service.quest_done_today(TID, 'compliment')
        assert not couple_service.quest_done_today(TID, 'dream')
        _say(uid, 'что тебе снилось?')
        assert couple_service.quest_done_today(TID, 'dream')
        assert not couple_service.quest_done_today(TID, 'day')
        _say(uid, 'день был длинный: с утра работа, потом спортзал, а вечером гуляли с другом по набережной')
        assert couple_service.quest_done_today(TID, 'day')
        assert not couple_service.quest_done_today(TID, 'voice')
        with SessionLocal() as s:
            s.add(ProductEvent(user_id=uid, character_id='anna_01', event_name='chat_user_message', metadata_json='{"kind": "voice"}'))
            s.commit()
        assert couple_service.quest_done_today(TID, 'voice')
    finally:
        with SessionLocal() as s:
            s.execute(delete(Message).where(Message.user_id == uid))
            s.execute(delete(ProductEvent).where(ProductEvent.user_id == uid))
            s.execute(delete(User).where(User.id == uid))
            s.commit()


def test_not_done_is_reported_not_credited():
    assert "return {'not_done': True}" in (ROOT / 'services' / 'couple_service.py').read_text(encoding='utf-8')
    assert "return web.json_response({'ok': False, 'error': 'not_done'}, status=409)" in MAIN
    assert "if (je.error === 'not_done') { toast(L.quest_not_done); closeFeature(); return; }" in INDEX


def test_apartment_intro_splash_and_save():
    assert 'aptintro' in INDEX and INDEX.count('apt_intro:') == 2
    head = INDEX[:INDEX.index('<body>')]
    assert '<script src="https://telegram.org/js/telegram-web-app.js"' not in head
    assert INDEX.index('id="bootSplash"') < INDEX.index('<script src="https://telegram.org/js/telegram-web-app.js"')
    assert 'hideBootSplash();' in INDEX and 'showGridRetry()' in INDEX
    assert "tg.downloadFile({ url: url, file_name: name })" in INDEX
    assert 'data-dl=' in INDEX and 'id="lbDownload"' in INDEX


def test_first_tab_is_visible_on_boot():
    # The characters section had no «active» class, so the app opened on a
    # blank page until the user tapped a nav button.
    assert '<section class="tab active" id="tab-characters">' in INDEX
