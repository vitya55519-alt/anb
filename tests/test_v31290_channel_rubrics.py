"""V3.129.0 — channel rubrics «🗳 Выбираете вы» and «💬 Диалог дня»."""
from pathlib import Path

from services import channel_rubrics as cr
from services import girl_of_day

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_polls_fit_telegram_limits():
    for q, opts in cr.POLLS:
        assert 0 < len(q) <= 300
        assert 2 <= len(opts) <= 10
        assert all(0 < len(o) <= 100 for o in opts)


def test_results_only_from_real_votes():
    assert cr.results_text('Кто?', [('А', 0), ('Б', 0)]) is None
    text = cr.results_text('Кто?', [('А', 1), ('Б', 3)])
    assert 'Вы выбрали: Б' in text and '75%' in text and '25%' in text and 'Проголосовали: 4' in text


def test_dialog_is_marked_staged_and_safe():
    for n in range(len(cr.DIALOGS)):
        cap = cr.dialog_caption('Аня', n)
        assert '(пример переписки)' in cap and 'Аня:' in cap
        assert len(cap) < 900


def test_dialog_link_opens_her_chat(monkeypatch):
    monkeypatch.setattr(girl_of_day, 'pool', lambda: ['anna_01'])
    assert girl_of_day.girl_from_payload('src_dlg_anna_01') == 'anna_01'
    assert girl_of_day.girl_from_payload('src_girlday_anna_01') == 'anna_01'
    assert girl_of_day.girl_from_payload('src_dlg_nobody') is None


def test_poll_results_stored_per_message():
    cr.save_poll_results(987654, 'итог')
    assert cr.poll_results(987654) == 'итог'
    assert cr.poll_results(123) is None


def test_admin_wiring():
    assert "callback_data='chpost:poll'" in MAIN and "callback_data='chpost:dlg'" in MAIN
    body = MAIN.split('async def admin_chpost_cb(cq: types.CallbackQuery):', 1)[1].split('\nasync def ', 1)[0]
    assert 'ADMIN_TELEGRAM_IDS' in body.split('\n')[1]
    assert 'stop_poll' in body and 'is_anonymous=True' in body
