"""V3.137.0: a direct «разденься» / «undress» leads to a paid single «Раздеть»,
not to ordinary text. A bought credit opens the spicy gate, is spent only after
a successful render, and survives a failed one."""
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
PPS = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')


def _tid():
    return 9_300_000 + uuid.uuid4().int % 999_999


def test_direct_undress_detector_ru_en():
    import main
    for said in ('разденься', 'Раздевайся', 'раздень себя', 'сними всё', 'сними одежду',
                 'хочу тебя голой', 'хочу увидеть тебя голой',
                 'undress', 'undress yourself', 'get naked', 'take everything off',
                 'take off your clothes', 'i want you naked', 'strip', 'strip for me'):
        req = main._direct_undress_request(said)
        assert req is not None and req.scene == 'lingerie', said


def test_negations_and_ordinary_text_are_not_undress():
    import main
    for said in ('не раздевайся', 'нет, не надо', 'нельзя раздеваться',
                 "don't undress", 'do not get naked', 'no strip',
                 'привет', 'как дела?', 'расскажи о себе', 'покажи селфи',
                 'сними платье пожалуйста', '', '   '):
        assert main._direct_undress_request(said) is None, said


def test_credit_opens_spicy_gate_without_premium(monkeypatch):
    import main
    from services import undress_credits
    tid = _tid()
    monkeypatch.setattr(main, '_card_girl_photo_locked', lambda *a: False)
    monkeypatch.setattr(main, 'is_adult_confirmed', lambda *a: True)
    monkeypatch.setattr(main, 'is_premium', lambda *a: False)
    monkeypatch.setattr(main, 'get_relationship_stage', lambda *a: 1)
    monkeypatch.setattr(main, 'track_event', lambda *a, **k: None)
    # no credit yet -> Premium paywall
    assert main._chat_photo_gate(tid, 'anna_01', 'lingerie', undress_credit=True) == 'spicy'
    # a bought credit opens exactly this request, and the gate does not spend it
    undress_credits.add(tid, 1)
    assert main._chat_photo_gate(tid, 'anna_01', 'lingerie', undress_credit=True) is None
    assert undress_credits.balance(tid) == 1
    # without the undress flag the same credit does not bypass the paywall
    assert main._chat_photo_gate(tid, 'anna_01', 'lingerie', undress_credit=False) == 'spicy'


def test_adult_gate_still_blocks_a_credit(monkeypatch):
    import main
    from services import undress_credits
    tid = _tid()
    undress_credits.add(tid, 1)
    monkeypatch.setattr(main, '_card_girl_photo_locked', lambda *a: False)
    monkeypatch.setattr(main, 'is_adult_confirmed', lambda *a: False)
    monkeypatch.setattr(main, 'is_premium', lambda *a: False)
    monkeypatch.setattr(main, 'track_event', lambda *a, **k: None)
    assert main._chat_photo_gate(tid, 'anna_01', 'lingerie', undress_credit=True) == 'adult'
    assert undress_credits.balance(tid) == 1


def test_credit_spend_only_when_available():
    from services import undress_credits
    tid = _tid()
    assert undress_credits.balance(tid) == 0
    assert undress_credits.spend(tid) is False  # nothing to spend
    undress_credits.add(tid, 2)
    assert undress_credits.balance(tid) == 2
    assert undress_credits.spend(tid) is True
    assert undress_credits.balance(tid) == 1
    assert undress_credits.spend(tid) is True
    assert undress_credits.balance(tid) == 0
    assert undress_credits.spend(tid) is False


def test_prelude_marks_direct_undress_and_blocked_offer():
    turn = MAIN[MAIN.index('async def _webapp_chat_turn('):MAIN.index('async def _webapp_api_chat_send(')]
    assert 'direct_undress = _direct_undress_request(text) is not None' in turn
    assert "pay = 'undress_credit'" in turn
    assert 'return (uid, scene, block, pay, direct_undress)' in turn
    assert "blocked_extra.update({'undress_offer': True, 'retry_text': text})" in turn
    assert '_chat_photo_blocked, uid, character_id, photo_block, blocked_extra' in turn


def test_single_credit_skips_pool_free_allowance_and_peaches():
    turn = MAIN[MAIN.index('async def _webapp_chat_turn('):MAIN.index('async def _webapp_api_chat_send(')]
    # no ready-made pool for a paid single «Раздеть»
    assert "pooled = None if pay == 'undress_credit' else" in turn
    # the credit is spent, not the free photo of the day and not peaches
    assert "if pay == 'undress_credit':" in turn
    assert 'undress_credits.spend(telegram_id)' in turn


def test_background_job_spends_credit_only_on_success():
    assert 'spend_undress_credit: bool = False' in MAIN
    assert 'if sent and spend_undress_credit:' in MAIN
    assert 'skip_stage=spend_undress_credit' in MAIN
    # a fresh buyer at level 1 still gets the photo he paid for
    assert 'skip_stage: bool = False' in PPS
    assert 'if not skip_stage and not scene_allowed_for_stage(request.scene, stage):' in PPS


def test_credit_status_endpoint_and_spa_retry():
    assert "app.router.add_get('/webapp/api/undress-credit'" in MAIN
    assert 'async def _webapp_api_undress_credit(' in MAIN
    assert 'waitForUndressReady' in SPA
    assert "quickBuy('undress'" in SPA or 'quickBuy(kind' in SPA
    assert 'data-retry' in SPA and 'data-buy' in SPA
    assert 'j.undress_offer' in SPA