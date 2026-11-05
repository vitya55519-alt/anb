"""V3.103.0 — the app-chat gate really blocks.

aiohttp < 3.11 (pinned by aiogram 3.15) has no StreamResponse.__bool__ and
its __len__ is 0, so ``if gate:`` was always False: the daily limit, the
18+ consent and the locked-card checks of the Mini App chat never stopped
anyone (backup 5 Nov: 1905 «sleep blocks» answered anyway).
"""
import re
from pathlib import Path

MAIN = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')


def test_gate_checked_against_none():
    calls = re.findall(r'gate = await asyncio\.to_thread\(_webapp_chat_gate[^\n]*\n\s*(if [^\n]*)', MAIN)
    assert len(calls) == 3
    assert all(c == 'if gate is not None:' for c in calls)
    assert not re.search(r'^\s*if gate:\s*$', MAIN, re.M)
