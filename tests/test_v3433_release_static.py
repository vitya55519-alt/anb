"""V3.43.3 static pins: plain photo cards, admin card-media swap, support /start.

The owner asked for five things at once:

1. «сделай просто фото» — the storefront grid shows a PLAIN static photo (the
   canonical look shot) instead of the Ken-Burns webp / i2v loops;
2. «дай мне возможность через админку менять карточки… вставлять фото и видео
   и гиф» — the admin panel card page gained «📥 Медиа витрины» / «🧹 Убрать
   медиа»: the sent photo/gif/webp/mp4 lands in ``data/card_media/<id>/`` and
   the grid renders it at once (jpg/png/webp/gif via <img>, mp4 via <video>);
3. the support bot answers /start with a welcome line (Come Closer benchmark:
   «Напишите ваше обращение и менеджер с вами свяжется») and forwards every
   appeal to the admins — a second aiogram bot inside this process, token
   from env only;
4. «какая она заявленная должна быть?» — the figure is DECLARED now: every
   built-in heroine follows the one house archetype (full silicone bust,
   Russian size 5, E cup, wasp waist, round lifted hips) via BODY_SPECS +
   the BODY IDENTITY prompt line — no flat girls, no per-scene drift;
5. «общаюсь с одним и тем же» — the heroines pace their own courtship:
   per-character bond tempo (CHARACTER_PACE in apply_delta) and per-character
   stage texture (PACE_HINTS in build_relationship_context).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
PHOTO_SVC = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
REL_ENGINE = (ROOT / 'services' / 'relationship_engine.py').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    # V3.43.3 shipped this; newer releases keep the pin in their own suite.
    assert VERSION in ('3.43.4', '3.43.3')


# ── 1. the grid card is a plain static photo ────────────────────────────────

def test_grid_card_defaults_to_the_static_look_photo():
    assert "else f\"/webapp/photo/{card.character_id}?i=1&v={ver}\")" in WEBAPP_SVC
    # no Ken-Burns webp and no i2v loop in the default chain anymore
    assert "'/webapp/gif/{card.character_id}" not in WEBAPP_SVC
    assert "'/webapp/live/{card.character_id}" not in WEBAPP_SVC


# ── 2. admin-uploaded card media ────────────────────────────────────────────

def test_card_media_override_storage():
    assert "CARD_OVERRIDE_EXTS = ('.mp4', '.webp', '.gif', '.png', '.jpg')" in WEBAPP_SVC
    assert 'def card_media_folder(character_id: str) -> Path:' in WEBAPP_SVC
    assert "return ROOT / 'data' / 'card_media' / character_id" in WEBAPP_SVC
    assert 'def character_card_override(character_id: str) -> Path | None:' in WEBAPP_SVC
    assert 'def set_card_override(character_id: str, data: bytes, ext: str) -> Path:' in WEBAPP_SVC
    assert 'def clear_card_override(character_id: str) -> bool:' in WEBAPP_SVC
    # the override re-stamps the ?v= URLs
    assert 'folders.append(card_media_folder(character_id))' in WEBAPP_SVC


def test_admin_panel_media_swap_flow():
    assert 'CARD_MEDIA_WAIT: dict[int, str] = {}' in MAIN
    assert "InlineKeyboardButton(text='📥 Медиа витрины', callback_data=f'admin:cardmedia:{character_id}')" in MAIN
    assert "InlineKeyboardButton(text='🧹 Убрать медиа', callback_data=f'admin:cardclear:{character_id}')" in MAIN
    assert "@dp.callback_query(F.data.startswith('admin:cardmedia:'))" in MAIN
    assert "@dp.callback_query(F.data.startswith('admin:cardclear:'))" in MAIN
    assert 'async def admin_card_media_upload(message: types.Message):' in MAIN
    # the waiting handler only fires while an admin session is armed
    assert 'lambda m: m.from_user is not None and m.from_user.id in CARD_MEDIA_WAIT' in MAIN
    # telegram-side download + the 20 MB bot-api ceiling
    assert 'await bot.download(file_id, destination=buf)' in MAIN
    assert 'if size > 20 * 1024 * 1024:' in MAIN
    # the summary line shows what the grid renders right now
    assert "f'Медиа витрины: {_admin_card_media_label(character_id)}\\n\\n'" in MAIN
    # /cancel drops the wait session
    assert 'if message.from_user.id in CARD_MEDIA_WAIT:' in MAIN


def test_card_media_route_serves_the_override():
    assert 'async def _webapp_card(request: web.Request) -> web.Response:' in MAIN
    assert "add_get('/webapp/card/{character_id}', _webapp_card)" in MAIN
    # the grid payload points photo-ish overrides at <img> and mp4 at <video>
    assert "'card': (f'/webapp/card/{card.character_id}?v={ver}'" in WEBAPP_SVC
    assert "if ov_ext in ('.jpg', '.png', '.webp', '.gif')" in WEBAPP_SVC
    assert "'live': (f'/webapp/card/{card.character_id}?v={ver}'" in WEBAPP_SVC
    assert "if ov_ext == '.mp4' else None" in WEBAPP_SVC


# ── 3. the support bot welcomes and forwards ────────────────────────────────

def test_support_bot_welcome_and_forward():
    assert 'SUPPORT_BOT_TOKEN = os.getenv("SUPPORT_BOT_TOKEN", "").strip()' in CONFIG
    assert 'SUPPORT_WELCOME_TEXT = os.getenv(' in CONFIG
    assert 'Напишите ваше обращение и менеджер с вами свяжется.' in CONFIG
    assert 'async def _run_support_bot() -> None:' in MAIN
    assert '@support_dp.message(Command(\'start\'))' in MAIN
    assert 'await msg.answer(SUPPORT_WELCOME_TEXT)' in MAIN
    assert 'await msg.forward(chat_id=admin_id)' in MAIN
    assert 'Приняла твоё обращение ✅ Менеджер свяжется с тобой вскоре.' in MAIN
    # startup gate: no token — no polling, just a warning
    assert 'if SUPPORT_BOT_TOKEN:' in MAIN
    assert 'asyncio.create_task(_run_support_bot())' in MAIN
    assert 'SUPPORT_BOT_TOKEN empty — the support bot stays offline' in MAIN


# ── 4. the declared figure: one house archetype, no flat girls ──────────────

def test_body_specs_follow_the_house_archetype():
    # every built-in heroine is declared as size 5, E cup — the owner's
    # «большая грудь, спортивная, пышная, талия тонкая, плоских не генерировать»
    for cid in ('alena_01', 'maria_01', 'erika_01', 'sonya_01', 'vika_01', 'alisa_01', 'mila_01'):
        line = next((ln for ln in PHOTO_SVC.splitlines() if f"'{cid}':" in ln and 'hourglass' in ln), '')
        assert 'wasp waist' in line and 'Russian size 5, E cup' in line, cid
    # the default for heroines without a spec (and any future one) is NOT flat
    assert 'and a full bust (silicone, Russian size 5, E cup)' in PHOTO_SVC
    assert 'size 4, D cup' not in PHOTO_SVC
    # the identity prompt carries the BODY IDENTITY line built from the spec
    assert "body_line = (" in PHOTO_SVC
    assert "f'BODY IDENTITY: {name} has {body_spec}. Preserve this exact figure in every photo '" in PHOTO_SVC


# ── 5. per-character courtship: own tempo, own stage texture ────────────────

def test_relationship_growth_follows_character_pace():
    assert 'CHARACTER_PACE = {' in REL_ENGINE
    assert "'anna_01': 1.0," in REL_ENGINE  # Anna stays the benchmark
    # the tempos are deliberately spread — nobody copies Anna's ladder speed
    assert "'alena_01': 1.25," in REL_ENGINE  # Emily burns fast
    assert "'maria_01': 0.75," in REL_ENGINE  # Maria is a slow elegant burn
    assert "'sonya_01': 0.7," in REL_ENGINE   # Sonya is the slowest to warm up
    assert "'vika_01': 1.15," in REL_ENGINE   # Vika pushes hard
    assert 'def character_pace(character_id: str) -> float:' in REL_ENGINE
    # applied inside apply_delta — the single place all bond growth flows
    assert 'pace = character_pace(character_id)' in REL_ENGINE
    assert 'r = r * pace if r > 0 else r' in REL_ENGINE
    # penalties and decay are never amplified by the tempo
    assert 'if pace != 1.0:' in REL_ENGINE


def test_stage_context_carries_character_texture():
    # PACE_HINTS: how she LIVES the current stage, not just which stage it is
    assert 'PACE_HINTS = {' in REL_ENGINE
    for marker in ('Темперамент Анны', 'Темперамент Emily', 'Темперамент Марии',
                   'Темперамент Эрики', 'Темперамент Сони', 'Темперамент Вики',
                   'Темперамент Алисы', 'Темперамент Милы'):
        assert marker in REL_ENGINE
    # injected right after the stage narrative in build_relationship_context
    assert "pace_hint = PACE_HINTS.get(character_id, '')" in REL_ENGINE
    assert "+ pace_line + extra" in REL_ENGINE
