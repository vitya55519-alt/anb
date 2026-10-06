"""V3.55.3: «⭐ Премиум» — a THIRD segment tab (replaces the V3.55.2 section).

Owner direction (voice): three tabs — «🍑 Персиковый сад» | «👥 Сообщество» |
«⭐ Премиум». The premium tab is CLOSED for non-premium users: tapping it does
not switch, it toasts and opens the shop. Inside, the mechanics mirror the
community витрина (grid + add-character) but only for premium personas, and
only the owner (admin) may add one through the existing constructor.

1. Markup: a third ``<button data-seg="prem">`` in ``#charSeg``; the old
   ``#premSec`` under-grid section is gone.
2. The segment handler refuses to switch a non-premium user onto «prem» —
   it toasts ``L.need_premium`` and shows the shop tab instead.
3. ``renderCharacters`` buckets by segment: premium-status girls live only on
   «prem», the official tab drops them, and the community tab excludes them too
   so a girl never rides two tabs at once.
4. Creation: the community keeps the always-live ➕; the premium tab shows its
   own ➕ ONLY to an admin (``ME.admin``), opening the wizard with the premium
   flag on. The backend double-checks ADMIN_TELEGRAM_IDS.
5. The ⭐ tab dims for non-premium (lockedseg) and the existing paywall gates
   (doSelect / openCharPage / openCharacter) are untouched.
6. i18n: the new ``seg_premium`` key in all 7 locales.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_third_tab_markup_and_no_old_section():
    assert '<button data-seg="prem" id="segPrem"></button>' in INDEX
    assert 'document.getElementById(\'segPrem\').textContent = L.seg_premium;' in INDEX
    # the V3.55.2 under-grid section is fully removed
    assert 'id="premSec"' not in INDEX
    assert 'class="premsec"' not in INDEX


def test_prem_tab_closed_for_non_premium():
    # the click handler gates the switch behind ME.premium before assigning CHAR_SEG
    assert "if (seg === 'prem' && !(ME && ME.premium)) {" in INDEX
    assert 'toast(L.need_premium);' in INDEX
    assert "showTab('shop');" in INDEX


def test_three_way_segment_filter():
    # premium girls only on the prem tab; official + community both exclude them
    assert "if (CHAR_SEG === 'prem') {\n      if (c.status !== 'premium') return false;" in INDEX
    assert "} else if (CHAR_SEG === 'official') {\n      if (!!c.custom || c.status === 'premium') return false;" in INDEX
    assert "} else if (!c.custom || c.status === 'premium') return false;" in INDEX


def test_admin_only_premium_create_card():
    # community keeps the always-live ➕ (no create card on official/prem grid)
    assert "const createCard = (CHAR_SEG === 'community') ?" in INDEX
    # the premium ➕ is admin-gated and opens the wizard with the premium flag
    assert "if (CHAR_SEG === 'prem' && ME && ME.admin) {" in INDEX
    assert 'id="premCreateCard"' in INDEX
    assert "pcc.addEventListener('click', () => openWizard(true));" in INDEX
    # openWizard carries the flag into the draft body
    assert 'async function openWizard(premiumMode) {' in INDEX
    assert 'WIZ.premium = !!premiumMode;' in INDEX
    assert 'premium: !!WIZ.premium' in INDEX


def test_locked_tab_dim_and_gates_untouched():
    # non-premium dims the ⭐ tab
    assert "sp.classList.toggle('lockedseg', !(ME && ME.premium));" in INDEX
    assert '#charSeg button.lockedseg' in INDEX
    # the pre-existing paywall gates still key on card status (unchanged)
    assert INDEX.count("status === 'premium' && !(ME && ME.premium)") >= 3


def test_seg_premium_i18n_in_all_seven_locales():
    assert INDEX.count('seg_premium:') >= 7
