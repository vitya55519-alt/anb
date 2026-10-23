"""V3.81.0: past the daily free-photo budget, free chat photos come from the
pool; paid and Premium photos are untouched."""
import inspect


def test_budget_trips_after_rendered_free_photos(monkeypatch):
    from services.db import init_db
    init_db()
    from services import chat_photo_allowance as A
    from services.user_service import ensure_user
    monkeypatch.setattr(A, 'FREE_PHOTO_DAILY_BUDGET_USD', 0.07)
    monkeypatch.setattr(A, 'FREE_PHOTO_COST_USD', 0.035)
    base = A.free_photo_spend_today()
    uid = ensure_user(981001)
    if base >= 0.07:
        assert A.free_photo_budget_spent()
        return
    A.use_free_chat_photo(uid, 'anna_01')
    A.use_free_chat_photo(uid, 'anna_01')
    assert A.free_photo_budget_spent()
    # a pool-served free photo does not add to the bill
    before = A.free_photo_spend_today()
    A.use_free_chat_photo(uid, 'anna_01')
    A.note_today(uid, A.POOL_EVENT, 'anna_01')
    assert abs(A.free_photo_spend_today() - before) < 1e-9


def test_budget_off_never_trips(monkeypatch):
    from services import chat_photo_allowance as A
    monkeypatch.setattr(A, 'FREE_PHOTO_DAILY_BUDGET_USD', 0.0)
    assert A.free_photo_budget_spent() is False


def test_pool_only_for_free_non_premium_photos():
    import main
    src = inspect.getsource(main._free_photo_from_pool)
    assert 'ADMIN_TELEGRAM_IDS' in src and 'is_premium(telegram_id)' in src
    assert 'free_chat_photos_left(uid) <= 0' in src and 'free_photo_budget_spent()' in src
    assert "picked[2] != 'photo'" in src
