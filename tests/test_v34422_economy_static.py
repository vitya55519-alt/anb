"""Static regression tests for V3.44.22: the peach economy rework.

Owner requests (one release, four changes):
1. studio picture: 150 → 10 🍑 (the old price made one picture cost like
   five months of Premium);
2. character constructor: a persona published to «Сообщество» is FREE, a
   private one costs 10 🍑 — plus a polished creator cabinet (likes, summary
   totals, date, chat shortcut);
3. sane peach pack prices — explicit round ₽/★ instead of the
   PHOTO_COST_STARS × N ladder (250/675/1875 ★) that priced 100 peaches
   above three months of Premium;
4. «Поддержать проект»: the weekly reminder button opens an in-bot
   50/100/500 ₽ chooser paid through Platega; the external CloudTips link
   stays only as the Platega-off fallback.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
DONATION = (ROOT / 'services' / 'donation_service.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
ENV = (ROOT / '.env.example').read_text(encoding='utf-8')


# ── 1. peach pack ladder ───────────────────────────────────────────────────


def test_pack_prices_are_explicit_and_round():
    assert 'PEACH_PACK_10_STARS = int(os.getenv("PEACH_PACK_10_STARS", "50"))' in CONFIG
    assert 'PEACH_PACK_30_STARS = int(os.getenv("PEACH_PACK_30_STARS", "125"))' in CONFIG
    assert 'PEACH_PACK_100_STARS = int(os.getenv("PEACH_PACK_100_STARS", "350"))' in CONFIG
    assert 'PEACH_PACK_10_RUB = max(1, int(os.getenv("PEACH_PACK_10_RUB", "99")))' in CONFIG
    assert 'PEACH_PACK_30_RUB = max(1, int(os.getenv("PEACH_PACK_30_RUB", "249")))' in CONFIG
    assert 'PEACH_PACK_100_RUB = max(1, int(os.getenv("PEACH_PACK_100_RUB", "699")))' in CONFIG
    # the star-count inheritance that produced 250/675/1875 ★ is gone
    assert 'str(PHOTO_COST_STARS * 10)' not in CONFIG
    assert 'PEACH_PACK_30_STARS", str(int(PHOTO_COST_STARS * 30 * 0.9))' not in CONFIG


def test_platega_charges_the_real_pack_price():
    assert 'if product in PEACH_PACK_RUB:' in MAIN
    assert 'return PEACH_PACK_RUB[product]' in MAIN
    # the ladder guess is no longer the source of the card charge
    assert 'fiat_values(PEACH_PACK_STARS[product])[0]' not in MAIN


def test_shop_packs_carry_real_rub():
    for pack in ('10', '30', '100'):
        assert f"'rub': PEACH_PACK_{pack}_RUB if PLATEGA_ENABLED else None," in WEBAPP_SVC
    # honest per-peach discount badges (9.9 → 8.3 → 7.0 ₽)
    assert "'badge': '−16%'," in WEBAPP_SVC
    assert "'badge': '−29%'," in WEBAPP_SVC
    # the fiat ladder is no longer pre-computed for the packs
    assert 'p10_rub, p10_usd = fiat_values(PEACH_PACK_10_STARS)' not in WEBAPP_SVC


# ── 2. studio picture = 10 🍑 ──────────────────────────────────────────────


def test_studio_picture_costs_ten_peaches():
    assert 'WEBAPP_PICTURE_COST_CREDITS = 10' in WEBAPP_SVC
    assert "'Одна картинка — 10 🍑'" in INDEX
    assert "'Create · 10 🍑'" in INDEX
    # every locale dropped the dead 150
    assert '150 🍑' not in INDEX


def test_chat_photo_guard_matches_its_one_credit_charge():
    # a chat photo costs ONE credit (consume_photo_credit) — the guard used to
    # demand the studio's whole price and block users who could pay the charge
    start = MAIN.index("if kind == 'photo' and telegram_id not in ADMIN_TELEGRAM_IDS")
    media = MAIN[start:start + 700]
    assert 'get_photo_credits(telegram_id) < 1:' in media
    assert 'WEBAPP_PICTURE_COST_CREDITS' not in media
    # the STUDIO guard keeps charging the full studio price
    assert 'get_photo_credits(telegram_id) < webapp_service.WEBAPP_PICTURE_COST_CREDITS' in MAIN


# ── 3. constructor: public free, private 10 🍑 ─────────────────────────────


def test_constructor_peaches_config():
    assert 'CONSTRUCTOR_COST_PEACHES = max(1, int(os.getenv("CONSTRUCTOR_COST_PEACHES", "10")))' in CONFIG


def test_chat_constructor_branches_on_community():
    assert "is_public = str(params.get('community') or '') == 'community_yes'" in MAIN
    assert "'✅ Создать · бесплатно'" in MAIN
    assert "f'🍑 Создать приватную · {CONSTRUCTOR_COST_PEACHES} 🍑'" in MAIN
    # both the confirm keyboard and the buy handler free the public path
    assert "if str(cons['params'].get('community') or '') == 'community_yes':" in MAIN
    assert "'source': 'community_free'" in MAIN


def test_webapp_constructor_free_path():
    assert "if str((cons.get('params') or {}).get('community') or '') == 'community_yes':" in MAIN
    assert "'public_free': True," in MAIN


def test_characters_keyboard_teaser_matches_new_economy():
    assert 'Создать свою · бесплатно / {CONSTRUCTOR_COST_PEACHES} 🍑' in MAIN
    # the contradicting 50⭐ teaser and the separate rub row are gone
    assert 'Создать свою · {CONSTRUCTOR_COST_STARS}⭐' not in MAIN
    assert "'constructor_rub', CONSTRUCTOR_COST_RUB," not in MAIN


def test_wizard_frontend_community_pricing():
    assert "const isPublic = WIZ.params.community === 'community_yes';" in INDEX
    assert "const freeCreate = WIZ.free || isPublic;" in INDEX
    # the Stars fallback row is retired — private personas pay peaches only
    assert 'id="wizCreateStars"' not in INDEX
    assert "wiz_free_public: 'бесплатно — она появится в «Сообществе»'" in INDEX
    assert "constructor_price_note: p => 'публично — бесплатно · приватно — ' + p + ' 🍑'" in INDEX
    assert "'constructor_peaches': CONSTRUCTOR_COST_PEACHES," in WEBAPP_SVC


# ── 4. donation through Platega ────────────────────────────────────────────


def test_donation_amounts_config():
    assert 'os.getenv("DONATION_AMOUNTS_RUB", "50,100,500")' in CONFIG
    assert 'or (50, 100, 500)' in CONFIG


def test_donation_button_is_callback_when_platega_live():
    assert "callback_data='donate:open'" in DONATION
    # the CloudTips URL survives as the Platega-off fallback
    assert 'url=DONATION_LINK' in DONATION


def test_donation_chooser_rides_the_platega_handler():
    assert "f'platega:donation_{amount}'" in DONATION
    assert "for amount in DONATION_AMOUNTS_RUB" in DONATION


def test_donate_open_handler():
    assert "@dp.callback_query(F.data == 'donate:open')" in MAIN
    assert 'donation_service.donation_amounts_keyboard(lang)' in MAIN


def test_donation_amount_lookup_is_forgery_safe():
    assert "if product.startswith('donation_'):" in MAIN
    assert 'max(1, int(product.split(\'_\')[1]))' in MAIN


def test_donation_invoice_title():
    assert "f'💜 Поддержать проект — {amount} ₽'" in MAIN


def test_donation_confirm_and_ledger():
    # the callback chain thanks the donor and records the payment; the
    # record_payment ledger row still feeds the partner commission
    callback = MAIN[MAIN.index('async def _platega_callback(request: web.Request)'):MAIN.index('async def _platega_success')]
    assert "if product.startswith('donation_'):" in callback
    assert 'Спасибо за поддержку' in callback


# ── honest pay-method labels ───────────────────────────────────────────────


def test_pay_buttons_tell_the_truth():
    # the Platega page takes card / SBP / crypto — the labels say so now
    assert 'карта / СБП / крипта' in MAIN
    assert 'оплата картой / СБП / криптой' in MAIN
    assert "pay_sbp: 'Карта / СБП / крипта'" in INDEX
    assert 'СБП / карта' not in MAIN
    assert 'СБП / карта' not in INDEX


# ── creator cabinet polish ─────────────────────────────────────────────────


def test_creator_cabinet_has_likes_and_totals():
    assert "'likes': likes.get(str(row.character_id), 0)," in WEBAPP_SVC
    assert "'total_views': sum(int(c.get('views') or 0) for c in characters)," in WEBAPP_SVC
    assert "'total_likes': sum(int(c.get('likes') or 0) for c in characters)," in WEBAPP_SVC


def test_creator_cabinet_frontend_summary_and_chat():
    assert "creator_summary: s => 'Твои персонажи: ' + s," in INDEX
    assert 'creator_summary: s => \'Your characters: \' + s,' in INDEX
    assert 'data-chat-id="${esc(c.id)}"' in INDEX
    assert '👍 ${esc(fmtK(c.likes || 0))}' in INDEX


# ── env example documents the new knobs ────────────────────────────────────


def test_env_example_documents_new_knobs():
    assert 'PEACH_PACK_10_RUB=99' in ENV
    assert 'PEACH_PACK_30_RUB=249' in ENV
    assert 'PEACH_PACK_100_RUB=699' in ENV
    assert 'CONSTRUCTOR_COST_PEACHES=10' in ENV
    assert 'DONATION_AMOUNTS_RUB=50,100,500' in ENV
