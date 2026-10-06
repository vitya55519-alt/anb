"""V3.55.3 backend: premium-status enforcement for constructor personas.

The premium card status already gated built-ins everywhere; the two Mini App
chat endpoints had a custom-character branch that only checked EXISTENCE, so a
constructor persona flipped to premium was silently open to everyone. And a
premium persona created through the app wizard now has to actually register as
premium — but only when the creator is an admin.

1. ``_custom_premium_gate_block`` reads the card status and refuses a non-premium
   stranger, while letting premium users, admins and the AUTHOR through.
2. Both app chat endpoints (chat_send / chat_media) call it in the custom branch
   and return the SAME ``premium_required`` 403 the built-in branch uses (the SPA
   already maps that to the paywall toast + shop tab).
3. The app draft stores a premium flag on the session ONLY for admins, so a
   forged body flag can never mint a premium persona for a normal user.
4. ``_finish_constructor`` registers the card with ``status='premium'`` when that
   admin flag is present, else the usual ``'active'``.
5. The publish/moderation path still only flips ``is_visible`` — a custom premium
   persona keeps her premium status after approval.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CARDS = (ROOT / 'services' / 'character_card_service.py').read_text(encoding='utf-8')


def test_gate_helper_defined():
    assert 'def _custom_premium_gate_block(character_id: str, telegram_id: int) -> bool:' in MAIN
    assert "if not card or card.status != 'premium':" in MAIN
    # premium user / admin bypass, and the author keeps her own creation
    assert 'if is_premium(telegram_id) or telegram_id in ADMIN_TELEGRAM_IDS:' in MAIN
    assert 'return str(telegram_id) not in webapp_service._mine_character_ids(telegram_id)' in MAIN


def test_both_app_chat_endpoints_gate_custom_branch():
    # the exact helper call appears in chat_send AND chat_media custom branches
    assert MAIN.count('if _custom_premium_gate_block(character_id, telegram_id):') == 2
    # both return the same premium_required 403 shape the built-in branch uses
    assert MAIN.count("return web.json_response({'ok': False, 'error': 'premium_required'}, status=403)") >= 4


def test_draft_premium_flag_is_admin_only():
    assert "if body.get('premium') and telegram_id in ADMIN_TELEGRAM_IDS:" in MAIN
    assert "session_data['premium'] = True" in MAIN


def test_finish_constructor_registers_premium_status():
    assert ("card_status = ('premium' if cons.get('premium') and telegram_id in ADMIN_TELEGRAM_IDS"
            in MAIN)
    assert "else 'active')" in MAIN
    assert 'short_bio=bio, status=card_status, card_photo_file_id=avatar_file_id,' in MAIN
    assert 'update_card(row.character_id, status=card_status, card_photo_file_id=avatar_file_id, is_visible=False)' in MAIN


def test_premium_status_label_exists():
    # update_card validates against STATUS_LABELS — 'premium' must be a key
    assert '"premium":' in CARDS


def test_moderation_approval_keeps_status():
    # charmod approve only touches is_visible, never resets status
    assert 'update_card(character_id, is_visible=bool(approve))' in MAIN
