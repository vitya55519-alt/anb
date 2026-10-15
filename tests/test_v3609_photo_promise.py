"""V3.60.9: «лови фотку» always comes with a photo; failed renders reach the admin feed."""
import re
from pathlib import Path

from services.photo_service import parse_photo_request

MAIN = Path('main.py').read_text(encoding='utf-8')
SRC = MAIN[MAIN.index('PHOTO_PROMISE = re.compile('):MAIN.index('def _accepts_her_photo_offer')]
ns = {'re': re}
exec(SRC, ns)


def test_skin_photo_is_a_request():
    for t in ('ну скинь фотку', 'кидай фото', 'скинь фоточку'):
        assert parse_photo_request(t) is not None, t


def test_promise_regex():
    p = ns['PHOTO_PROMISE']
    for t in ('ну ладно, лови фотку для поднятия настроения 📸', 'держи селфи', 'только тихо смотри, не на рабстоле открывай 😏📸'):
        assert p.search(t), t
    for t in ('мне нравится фото с моря', 'я сегодня устала'):
        assert not p.search(t), t


def test_agree_after_offer():
    agree = ns['PHOTO_AGREE']
    assert agree.search('скинь конечно') and agree.search('давай') and agree.search('да')
    assert not agree.search('мне нравишься')


def test_promise_and_failures_wired():
    assert 'if PHOTO_PROMISE.search(answer or' in MAIN
    assert '_accepts_her_photo_offer(uid, character_id, text)' in MAIN
    assert MAIN.count('webapp_service.record_generation_failure') >= 6
    html = Path('webapp/index.html').read_text(encoding='utf-8')
    assert "const bad = g.engine === 'error'" in html


def test_test_stage_persists():
    src = Path('services/test_mode.py').read_text(encoding='utf-8')
    assert 'AdminTestStage' in src and '_db_write(user_id, stage)' in src


def test_free_limit_is_20():
    assert 'FREE_MESSAGES_PER_DAY", "20"' in Path('config.py').read_text(encoding='utf-8')


def test_level_snapshot_shape():
    from services.relationship_engine import level_snapshot
    snap = level_snapshot(None, None)
    assert snap['level'] == 1 and snap['next_title'] == 'Симпатия'
    assert [b['key'] for b in snap['bars']] == ['rel', 'trust', 'passion', 'talk']
    assert snap['messages_left'] > 0
    assert "app.router.add_get('/webapp/api/chat/level'" in MAIN
    html = Path('webapp/index.html').read_text(encoding='utf-8')
    assert 'function openLevelSheet()' in html and 'id="chatLvl"' in html


def test_breakup_is_softened():
    from services import chat_service as cs
    assert cs.BREAKUP.search('всё. не пиши мне. ни сегодня, ни завтра')
    assert 'elif BREAKUP.search(answer):' in Path('services/chat_service.py').read_text(encoding='utf-8')
    rules = Path('services/character_service.py').read_text(encoding='utf-8')
    assert 'Не обрывай общение' in rules


def test_photo_faces_never_sulky():
    from services import photo_expression_service as e
    assert 'neutral' not in e.LIVELY_VARIETY_KEYS and 'thoughtful' not in e.LIVELY_VARIETY_KEYS
    assert 'pout' in e.expression_description('upset', 'x')
