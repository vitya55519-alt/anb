"""V3.167.7 (владелец, скрин 16.11): «в режиме без цензуры открой все кнопки».

Лист «📸 Какое фото?» показывал серые строки «откроется на уровне 2/3» там, где
аккаунт уже выбрал «Без цензуры 18+». Режим обещает, что лесенки уровней для
смелых кадров нет (так же, как с Premium в V3.88.0), поэтому её снимает и здесь.

Что эти тесты держат:
* `scene_allowed_for_stage` с id аккаунта в режиме возвращает True, без id и
  без режима — прежнее поведение;
* сцена, которой нет в SCENE_LEVELS (снятые из генерации «peek»/«dressing»),
  остаётся закрытой и в режиме;
* клавиатура бота в режиме не рисует 🔒-строк сюжетов и отдаёт весь список;
* гейт Mini App (`_chat_photo_gate`) в режиме не отвечает 'stage';
* цены, Premium и 18+ режим не трогает.
"""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

import main
from models.app_models import Base, User
from services import explicit_mode as xm
from services.db import SessionLocal, engine
from services.photo_service import (
    PhotoRequest, scene_allowed_for_stage, scenes_open_in_explicit_mode,
    spicy_needs_premium,
)

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')

# сюжет уровня 4, который Premium не требует — ровно такая кнопка и была серой
SCENE = 'bar'


def _user() -> int:
    Base.metadata.create_all(engine)
    tid = int(f'96{datetime.now(timezone.utc).strftime("%H%M%S%f")}')
    with SessionLocal() as s:
        s.add(User(telegram_id=str(tid), name='t', timezone='UTC'))
        s.commit()
    return tid


def _buttons(kb) -> list[str]:
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]


def test_mode_opens_the_scene_and_nothing_else_changes():
    tid = _user()
    assert scenes_open_in_explicit_mode(tid) is False
    assert scene_allowed_for_stage(SCENE, 'stranger', tid) is False
    xm.set_mode(tid, True)
    assert scenes_open_in_explicit_mode(tid) is True
    assert scene_allowed_for_stage(SCENE, 'stranger', tid) is True
    # без id поведение прежнее — все старые вызовы ничего не потеряли
    assert scene_allowed_for_stage(SCENE, 'stranger') is False


def test_retired_scenes_stay_closed_in_the_mode():
    tid = _user()
    xm.set_mode(tid, True)
    # «peek»/«dressing» выведены из генерации: для них нет строки в SCENE_LEVELS
    assert scene_allowed_for_stage('peek', 'stranger', tid) is False
    assert scene_allowed_for_stage('dressing', 'stranger', tid) is False


def test_no_account_no_opening():
    assert scenes_open_in_explicit_mode(None) is False
    assert scenes_open_in_explicit_mode(0) is False


def test_photo_keyboard_in_the_mode_has_no_locked_scene_rows():
    tid = _user()
    main.ensure_user(tid, 't', language_code='ru')
    before = _buttons(main.photo_keyboard(tid))
    assert any(d.startswith('locked:') for d in before)
    assert f'photo:{SCENE}' not in before

    xm.set_mode(tid, True)
    after = _buttons(main.photo_keyboard(tid))
    for scene in main.PHOTO_MENU_ORDER:
        assert f'photo:{scene}' in after, scene
    # 🔒 остаётся только за платным кастомом — режим про содержимое, не про деньги
    assert [d for d in after if d.startswith('locked:')] in ([], ['locked:custom'])


def test_app_gate_lets_the_scene_through_in_the_mode():
    tid = _user()
    main.ensure_user(tid, 't', language_code='ru')
    assert main._chat_photo_gate(tid, 'anna_01', SCENE) == 'stage'
    xm.set_mode(tid, True)
    assert main._chat_photo_gate(tid, 'anna_01', SCENE) is None


def test_mode_does_not_touch_the_premium_gate():
    tid = _user()
    xm.set_mode(tid, True)
    assert scene_allowed_for_stage('nude', 'stranger', tid) is True
    # но кадр по-прежнему продаётся, а не раздаётся: Premium-гейт на месте
    assert spicy_needs_premium(PhotoRequest(scene='nude')) is True
    assert spicy_needs_premium(PhotoRequest(scene=SCENE)) is False


def test_the_menu_stops_painting_the_next_level_in_the_mode():
    # лист приложения: open_all снимает 'locked' со всех сюжетов
    assert "'locked': not open_all and SCENE_LEVELS.get(scene, 99) > level" in MAIN
    assert "open_all = scenes_open_in_explicit_mode(telegram_id)" in MAIN
    # ботовская строка «следующие фото откроются на уровне» в режиме гаснет
    assert "if scenes_open_in_explicit_mode(telegram_id):\n        future = []" in MAIN
