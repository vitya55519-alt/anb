"""V3.167.1 (владелец, Q3/Q4/Q6): три вещи одним релизом.

Q3 — в общем чате бота одна ветка на всех героинь, поэтому её строку подписывают
именем: «💬 Камила: …». Дефолтная Анна не подписывается: у неё чат свой, а лишний
префикс сломал бы теги и кнопки.
Q4 — шесть пустых личных заготовок топ-6 уходят из сида и из базы: витрина топ-6
крутится через 15 универсальных тизеров.
Q6 — карточка Лай снята с витрины и убрана из напарниц, Лизе возвращается
дочитанное био, а битое био (английский рефьюз, обрывок на середине слова) в
карточку не попадает вовсе.
"""
import asyncio
import logging

from sqlalchemy import delete, select

import services.greeting_service as gs
from models.app_models import CharacterCard, CharacterGreeting, ChatGuest
from services.character_card_service import STATUS_LABELS, ensure_default_cards
from services.custom_character_service import bio_is_publishable, write_card_bio
from services.db import SessionLocal, _drop_personal_greetings, _repair_character_cards, text
from services.heroine_label import PREFIX, label, stamp
from services.user_service import ensure_user

logging.getLogger('services.db').setLevel(logging.CRITICAL)

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
GIFT = (ROOT / 'services' / 'private_photo_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')

GREETING_MARKER = 'personal_greetings_removed_v31671'
CARD_MARKER = 'character_cards_repaired_v31671'
LAI = 'custom_6328140267_a4e61b58'
LIZA = 'custom_6237849550_257f28e7'
LIZA_BIO = ('Лиза знает, как одним взглядом заставить забыть обо всём. Её дерзкий '
            'характер и страстный темперамент превратят ваш вечер в игру без правил.')
TOP6 = ('anna_01', 'kamila_01', 'maria_01', 'liza_01', 'lana_01', 'kira_01')

ensure_default_cards()


def _clear_table():
    with SessionLocal() as s:
        s.execute(delete(CharacterGreeting))
        s.execute(text(f"DELETE FROM app_migrations WHERE name = '{GREETING_MARKER}'"))
        s.commit()


def _body(marker: str) -> str:
    """Тело функции main.py: от её объявления до следующего объявления верхнего
    уровня — чтобы статика не ловила совпадения из соседней функции."""
    start = MAIN.index(marker)
    tail = MAIN[start + 1:]
    cut = min(i for i in (tail.find('\nasync def '), tail.find('\ndef ')) if i != -1)
    return tail[:cut]


# ── Q3: метка героини ──────────────────────────────────────────────────

def test_the_default_heroine_is_never_labelled():
    assert label('') == ''
    assert label('anna_01') == ''
    assert stamp('скучала по тебе', 'anna_01') == 'скучала по тебе'


def test_every_other_heroine_signs_her_line():
    assert label('kamila_01') == f'{PREFIX}Камила: '
    assert stamp('скучала по тебе', 'kamila_01') == '💬 Камила: скучала по тебе'
    # уже подписанная строка второй подписи не получает
    assert stamp('💬 Камила: скучала', 'kamila_01') == '💬 Камила: скучала'
    assert stamp('', 'kamila_01') == ''
    # имени нет — значит и метки нет: «💬 :» он видеть не должен
    assert label('no_such_character_99') == ''


def test_her_live_answer_and_the_ceremony_carry_the_label():
    assert 'def _her_label(telegram_id: int) -> str:' in MAIN
    answer = _body('async def _send_answer_body(')
    assert 'her_tag = _her_label(message.from_user.id)' in answer
    assert 'await message.answer(her_tag + text)' in answer
    assert 'await message.answer(her_tag + part if i == 0 else part)' in answer
    assert 'caption=her_tag or None' in answer
    assert 'await bot.send_message(telegram_id, _her_label(telegram_id) + text)' in MAIN
    # Duo и роман называют говорящую сами — там метка не нужна.
    assert 'her_tag' not in _body('async def _send_duo_answer(')
    assert 'her_tag' not in _body('async def _send_novel_answer(')


def test_transferred_rails_keep_app_text_unlabelled_and_notify_generically():
    assert 'from services.heroine_label import stamp as _her' in SCHED
    # Remaining Telegram media previews retain their heroine label.
    assert "caption=_her(_ev.caption(text), char_id), reply_markup=markup)" in SCHED
    persist = SCHED[SCHED.index('def _to_app_chat('):SCHED.index('def _app_delivery(')]
    delivery = SCHED[SCHED.index('def _app_delivery('):SCHED.index('def _life_actions(')]
    # Her app dialog identifies her: store the raw text and its durable actions.
    assert "return save_message(uid, char_id, 'assistant', text, media_kind=media_kind," in persist
    assert 'origin=origin, actions=actions)' in persist
    assert '_her(' not in persist + delivery
    assert 'mid = _to_app_chat(uid, tg_id, char_id, text, shot, origin, actions)' in delivery
    assert delivery.index('if mid:') < delivery.index('app_ping.note(')
    assert "app_ping.note(bot, tg_id, char_id, ''," in delivery
    assert "channel='life' if origin == LIFE_ORIGIN else 'default', generic=True" in delivery
    assert 'return mid' in delivery and 'bot.send_' not in delivery


def test_telegram_photos_are_labelled_but_the_app_gift_is_not():
    assert 'from services.heroine_label import stamp as _her' in PHOTO
    assert 'caption = _her(caption or random.choice(AUTO_CAPTIONS' in PHOTO
    assert 'caption=_her(fallback_caption, character_id)' in PHOTO
    gift = GIFT[GIFT.index('async def send_daily_gift('):GIFT.index('# ─── Голос + фото комбо')]
    assert 'gift_char = user.selected_character or CHARACTER_ID' in gift
    assert '_to_app_chat(uid, telegram_id, gift_char, text, shot)' in gift
    assert '_her(' not in gift and 'bot.send_photo(' not in gift
    # сам кружок подписать нельзя: у Telegram video note нет подписи. Метка
    # достается обычному видео, куда кружок не влез.
    assert "caption=_her_label(telegram_id) + 'в кружок не поместилось 😅 держи так'" in MAIN
    assert 'await bot.send_video_note(chat_id, BufferedInputFile(video_bytes, filename=\'circle.mp4\'))' in MAIN


# ── Q4: пустые личные заготовки снесены ────────────────────────────────

def test_the_code_seeds_only_the_universal_hooks():
    assert not hasattr(gs, 'SEED_PERSONAL')
    _clear_table()
    assert gs.ensure_seed() == 30
    assert gs.ensure_seed() == 0
    with SessionLocal() as s:
        rows = list(s.scalars(select(CharacterGreeting)))
    assert {r.character_id for r in rows} == {'all'}
    assert {r.mode for r in rows} == {'spicy', 'normal'}
    _clear_table()


def test_the_greeting_migration_removes_his_old_six_rows():
    _clear_table()
    with SessionLocal() as s:
        for cid in TOP6:                                  # ids 1..6, как в проде
            s.add(CharacterGreeting(character_id=cid, mode='spicy', message_text='его сцена',
                                    buttons_json='[]', image_prompt='', reply_text=''))
        for _ in range(4):
            s.add(CharacterGreeting(character_id='all', mode='spicy', message_text='универсальная',
                                    buttons_json='[]', image_prompt='bedroom, lace', reply_text=''))
        s.commit()

    _drop_personal_greetings()

    with SessionLocal() as s:
        rows = list(s.scalars(select(CharacterGreeting).order_by(CharacterGreeting.id)))
        assert [r.character_id for r in rows] == ['all'] * 4, rows
        assert s.execute(text(f"SELECT 1 FROM app_migrations WHERE name = '{GREETING_MARKER}'")).first()
    _clear_table()
    with SessionLocal() as s:
        for cid in TOP6:
            s.add(CharacterGreeting(character_id=cid, mode='spicy', message_text='его сцена',
                                    buttons_json='[]', image_prompt='', reply_text=''))
        s.commit()
    _drop_personal_greetings()                            # флаг снят — прогон повторился
    with SessionLocal() as s:
        assert s.scalar(select(CharacterGreeting).where(CharacterGreeting.character_id == 'anna_01')) is None
    _clear_table()


# ── Q6: карточки ──────────────────────────────────────────────────────

def test_hidden_is_a_legal_card_status():
    from services.character_card_service import update_card
    assert STATUS_LABELS['hidden'] == 'скрыта'
    ensure_user(559411, 'hiddenstatus', language_code='ru')
    view = update_card('custom_test_hidden_01', display_name='Тест', short_bio='проба',
                       status='hidden', is_visible=False)
    assert view.status == 'hidden' and view.is_visible is False
    with SessionLocal() as s:
        s.execute(delete(CharacterCard).where(CharacterCard.character_id == 'custom_test_hidden_01'))
        s.commit()


def _seed_fake_cards() -> int:
    uid = ensure_user(559412, 'cardrepair', language_code='ru')
    with SessionLocal() as s:
        s.execute(text(f"DELETE FROM app_migrations WHERE name = '{CARD_MARKER}'"))
        s.execute(delete(CharacterCard).where(CharacterCard.character_id.in_([LAI, LIZA])))
        s.add(CharacterCard(character_id=LAI, display_name='Лай', gender='female', age=27,
                            short_bio='Лай любит ночь', status='active', button_emoji='👩',
                            is_visible=True))
        s.add(CharacterCard(character_id=LIZA, display_name='Лиза', gender='female', age=24,
                            short_bio='Лиза знает, как одним', status='active', button_emoji='👩',
                            is_visible=True))
        s.execute(text("DELETE FROM chat_guests WHERE guest_id = :c"), {'c': LAI})
        s.add(ChatGuest(user_id=uid, character_id='kamila_01', guest_id=LAI))
        s.commit()
    return uid


def _unseed_fake_cards():
    with SessionLocal() as s:
        s.execute(delete(CharacterCard).where(CharacterCard.character_id.in_([LAI, LIZA])))
        s.execute(text("DELETE FROM chat_guests WHERE guest_id = :c"), {'c': LAI})
        s.execute(text(f"DELETE FROM app_migrations WHERE name = '{CARD_MARKER}'"))
        s.commit()


def test_the_card_migration_hides_lai_and_repairs_liza():
    _seed_fake_cards()
    _repair_character_cards()
    with SessionLocal() as s:
        lai = s.get(CharacterCard, LAI)
        assert lai.is_visible is False and lai.status == 'hidden'
        assert not s.execute(text("SELECT 1 FROM chat_guests WHERE guest_id = :c"), {'c': LAI}).first()
        assert s.get(CharacterCard, LIZA).short_bio == LIZA_BIO
    _repair_character_cards()                             # флаг стоит — второй прогон молчит
    with SessionLocal() as s:
        assert s.get(CharacterCard, LIZA).short_bio == LIZA_BIO
    _unseed_fake_cards()


def test_both_migrations_run_at_startup():
    init = DB[DB.index('def init_db():'):]
    assert 'def _drop_personal_greetings() -> None:' in DB
    assert 'def _repair_character_cards() -> None:' in DB
    assert '_drop_personal_greetings()' in init
    assert '_repair_character_cards()' in init


# ── Q6: валидация био ─────────────────────────────────────────────────

def test_a_finished_russian_teaser_passes():
    assert bio_is_publishable(LIZA_BIO)
    assert bio_is_publishable('Она помнит, как ты просил не торопиться. Сегодня у неё другой план — '
                              'и он помещается в один вечер.')


def test_an_english_refusal_never_reaches_the_storefront():
    assert not bio_is_publishable("I'm sorry, but I can't write a description like that for you.")
    assert not bio_is_publishable('As an AI assistant, I cannot generate this kind of content here.')
    assert not bio_is_publishable('I cannot help with that request, sorry.')


def test_a_cut_off_short_or_oversized_bio_is_dropped():
    assert not bio_is_publishable('Лиза знает, как одним взглядом заставить забыть обо всём. Её дерзкий')
    assert not bio_is_publishable('Она ждёт')
    assert not bio_is_publishable('И вот она идёт по коридору и ')
    assert not bio_is_publishable('Она помнит. ' * 40)
    assert not bio_is_publishable('')


def test_the_constructor_keeps_the_template_when_the_model_refuses(monkeypatch):
    import services.llm_provider_service as llm

    async def refusal(messages, **kw):
        return llm.LLMResult("I can't write a description like that for you, sorry.",
                             'minimax', 'MiniMax-M3', True)

    monkeypatch.setattr(llm, 'generate_text', refusal)
    assert asyncio.run(write_card_bio({'temperament': 'temper_bold'}, 'Лиза')) is None
