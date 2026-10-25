"""V3.85.0: the partner program is a bottom-nav tab with art; profile cleaned."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')


def test_partner_is_a_bottom_tab():
    assert '<button data-tab="partner"><span class="ico">💸</span>' in INDEX
    assert '<section class="tab" id="tab-partner">' in INDEX
    assert "if(id==='partner'){loadPartner();}" in INDEX
    assert "if (sp.get('open') === 'partner') { showTab('partner'); return; }" in INDEX
    # every NAV_LABELS row has seven slots
    import re
    rows = re.findall(r"  (ru|en|es|it|fr|zh|ja): \[([^\]]*)\],", INDEX[INDEX.index('const NAV_LABELS'):])
    assert len(rows) == 7 and all(len(r[1].split(',')) == 7 for r in rows)


def test_partner_art_served_and_present():
    for name in ('partner_hero.jpg', 'step_share.png', 'step_chat.png', 'step_earn.png'):
        assert (ROOT / 'webapp' / 'art' / name).is_file(), name
        assert name in INDEX
    assert "app.router.add_get('/webapp/art/{name}', _webapp_art)" in MAIN
    assert "_WEBAPP_ART_RE = re.compile(r'^[a-z0-9_]{1,40}\\.(jpg|png|webp)$')" in MAIN


def test_partner_payload_carries_friend_rule():
    assert "'qualify_messages': REFERRAL_QUALIFY_MESSAGES," in WEB
    assert "'waiting': waiting," in WEB


def test_profile_no_longer_shows_level_girl_author_income():
    i = INDEX.index('function renderProfileBody() {')
    body = INDEX[i:i + 6000]
    assert 'selected_character.level' not in body
    assert 'L.selected_girl' not in body
    assert 'author_earnings' not in body
    assert 'menuPartner' not in body.split('const mp = ')[0]
