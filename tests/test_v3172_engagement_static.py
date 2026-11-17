"""Static regression tests for v3.17.2: underwear layering fix, video chain
diagnostics + Replicate polling, gift-of-day discount, voice notes after
gifts/dates, and the 7-day-streak free date voucher."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
CLOUD = (ROOT / 'services' / 'cloud_video_service.py').read_text(encoding='utf-8')
GIFTS = (ROOT / 'services' / 'gifts_service.py').read_text(encoding='utf-8')
GAMIF = (ROOT / 'services' / 'gamification_service.py').read_text(encoding='utf-8')


def test_replicate_uses_explicit_polling_not_run_wait():
    # replicate.run(wait=600) returned an unfinished prediction (API caps the
    # wait window at 60s) — the engine now creates the prediction and polls.
    assert 'replicate.run' not in CLOUD
    assert 'client.predictions.create' in CLOUD
    assert "prediction.status not in ('succeeded', 'failed', 'canceled')" in CLOUD
    assert 'await asyncio.to_thread(prediction.reload)' in CLOUD
    assert "raise CloudVideoError(f'replicate_timeout:" in CLOUD


def test_video_failure_reports_full_engine_chain_to_admin():
    assert 'engine_errors: list[str] = []' in MAIN
    assert "engine_errors.append(f'{engine_name}:" in MAIN
    assert "f'движки: {configured}\\n'" in MAIN
    assert "f'цепочка: {chain[:600]}'" in MAIN


def test_geministatus_lists_the_video_engine():
    start = MAIN.index("Command('geministatus')")
    block = MAIN[start:MAIN.index('@dp.', start)]
    # V3.69.0: one engine left
    assert 'Video (SpicyAPI):' in block
    assert 'spicy_video_available()' in block

def test_gift_of_the_day_catalog_logic():
    assert 'DAILY_DISCOUNT = 0.30' in GIFTS
    assert 'def get_daily_featured(' in GIFTS
    assert 'def effective_cost(' in GIFTS
    assert 'toordinal() % len(GIFTS)' in GIFTS
    assert 'max(1, round(gift.cost * (1 - DAILY_DISCOUNT)))' in GIFTS


def test_gift_of_the_day_wired_in_main():
    assert 'gifts_service.is_featured(g)' in MAIN
    assert 'подарок дня' in MAIN
    # Invoice and pre_checkout both use the discounted price.
    assert "f'gift:{gift.id}', gifts_service.effective_cost(gift))" in MAIN
    assert 'amount == gifts_service.effective_cost(gift)' in MAIN


def test_voice_note_after_gift_and_date():
    functions = {node.name: node for node in ast.parse(MAIN).body
                 if isinstance(node, ast.AsyncFunctionDef)}
    voice = functions['_send_voice_note']
    assert any(isinstance(node, ast.Call) and ast.unparse(node) ==
               "getattr(user, 'voice_enabled', False)" for node in ast.walk(voice))
    synth = next(node for node in ast.walk(voice) if isinstance(node, ast.Call)
                 and ast.unparse(node.func) == 'synthesize_bytes')
    assert any(kw.arg == 'character_id' and ast.unparse(kw.value) == 'character_id'
               for kw in synth.keywords)

    # Scope the paid gift branch, not pre-checkout or the admin-only preview.
    gift = next(node for node in functions['successful_payment'].body
                if isinstance(node, ast.If) and ast.unparse(node.test) == "payload.startswith('gift:')")
    date = functions['_deliver_date_reward']
    for reward, args in ((gift, ['message.chat.id', 'message.from_user.id', 'gift.reaction']),
                         (date, ['chat_id', 'telegram_id', 'date.text'])):
        calls = [node for node in ast.walk(reward) if isinstance(node, ast.Call)
                 and ast.unparse(node.func) == '_send_voice_note']
        assert len(calls) == 1
        assert [ast.unparse(arg) for arg in calls[0].args] == args
        assert {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords} == {
            'app_only': 'True', 'character_id': 'character_id'}
        assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                       and node.func.attr in {'send_voice', 'answer_voice', 'send_photo', 'answer_photo'}
                       for node in ast.walk(reward))
    photo = next(node for node in ast.walk(date) if isinstance(node, ast.Call)
                 and ast.unparse(node.func) == '_start_photo_background')
    assert {kw.arg: ast.unparse(kw.value) for kw in photo.keywords} == {
        'app_only': 'True', 'character_id': 'character_id'}


def test_free_date_voucher_service():
    assert 'FREE_DATE_STREAK = 7' in GAMIF
    assert 'def grant_free_date_voucher(' in GAMIF
    assert 'def has_free_date(' in GAMIF
    assert 'def consume_free_date(' in GAMIF
    assert "'free_date_grant'" in GAMIF and "'free_date_used'" in GAMIF
    # Granted on the 7-day streak milestone.
    assert 'if streak >= FREE_DATE_STREAK' in GAMIF


def test_free_date_wired_in_dates_flow():
    start = MAIN.index("kb_pair('date')")
    block = MAIN[start:MAIN.index("@dp.callback_query(F.data.startswith('date_locked:'))")]
    assert 'has_free_date' in block
    assert 'consume_free_date' in block
    assert 'бесплатное свидание за неделю стрика' in block
    assert 'Бесплатное свидание за твой стрик' in block
    assert "track_event(ensure_user(cq.from_user.id), 'free_date_used'" in block
    assert 'await _deliver_date_reward(cq.message.chat.id' in block


def test_yacht_premium_gift_exists():
    assert "Gift('yacht', 'Прогулка на яхте', '🛥', 50, 10.0," in GIFTS


def test_date_collection_and_achievements():
    # Catalog helper + completion tracking from relationship events.
    assert 'def get_all() -> list[Date]:' in (ROOT / 'services' / 'dates_service.py').read_text(encoding='utf-8')
    assert 'def completed_date_ids(' in GAMIF
    for key in ("'first_gift'", "'first_date'", "'ten_dates'", "'date_collector'"):
        assert key in GAMIF
    # Unlocks are wired into the gift and date reward paths.
    assert "unlock_achievement(message.from_user.id, 'first_gift')" in MAIN
    assert "unlock_achievement(telegram_id, 'first_date')" in MAIN
    assert "unlock_achievement(telegram_id, 'ten_dates')" in MAIN
    assert "unlock_achievement(telegram_id, 'date_collector')" in MAIN
    # The dates menu shows the collection state.
    assert 'Свиданий в коллекции' in MAIN
    assert '✅' in MAIN


def test_admin_can_test_gifts_and_dates_without_stars():
    # Admin clicks deliver the gift/date instantly — no invoice, no voucher.
    gift = MAIN[MAIN.index('async def gift_buy('):]
    gift = gift[:gift.index('@dp.', 10)]
    assert 'if cq.from_user.id in ADMIN_TELEGRAM_IDS:' in gift
    assert "'admin_test_gift'" in gift
    assert 'админ-тест: Stars не списаны' in gift
    assert 'await _send_voice_note(cq.message.chat.id, cq.from_user.id, gift.reaction)' in gift
    date = MAIN[MAIN.index('async def date_start('):]
    date = date[:date.index('@dp.', 10)]
    assert 'if cq.from_user.id in ADMIN_TELEGRAM_IDS:' in date
    assert "'admin_test_date'" in date
    assert 'await _deliver_date_reward(cq.message.chat.id' in date
    # Admin bypass runs before the free-date voucher is consumed.
    assert date.index('ADMIN_TELEGRAM_IDS') < date.index('has_free_date(cq.from_user.id)')
