"""V3.34.0 static checks: the Mini App becomes functional — Stars purchases
(createInvoiceLink + tg.openInvoice reusing the bot's payment handlers) and
character selection straight from the storefront grid."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_version_bumped():
    assert VERSION in ('3.44.4', '3.44.3', '3.43.7', '3.43.6', '3.43.5', '3.43.4', '3.43.3', '3.43.2', '3.43.1', '3.43.0', '3.42.2', '3.42.1', '3.42.0', '3.41.0', '3.40.0', '3.33.1', '3.34.0', '3.34.1', '3.35.0', '3.36.0', '3.37.0', '3.38.0', '3.39.0')


def test_invoice_products_declared():
    # Two standalone products: Premium (existing payload) and a new photo
    # credit pack. Payloads must match what the payment handlers validate.
    assert 'def api_invoice_products(' in WEBAPP_SVC
    assert "'payload': 'premium_month'" in WEBAPP_SVC
    # V3.43.1: the single-credit square became the peach pack ladder.
    assert "'payload': 'peach_pack_100'" in WEBAPP_SVC
    assert "'id': 'premium'" in WEBAPP_SVC
    assert "'id': 'peach_pack_10'" in WEBAPP_SVC
    # both RU and EN titles exist
    assert '10 персиков' in WEBAPP_SVC
    assert '10 peaches' in WEBAPP_SVC
    # the shop payload exposes the purchasable items
    assert "'purchases': api_invoice_products(lang)" in WEBAPP_SVC


def test_invoice_route_creates_links():
    handler = MAIN[MAIN.index('async def _webapp_api_invoice('):MAIN.index('async def _webapp_api_select(')]
    # initData HMAC gate before anything else
    assert 'validate_init_data' in handler
    assert "status=401" in handler
    # only declared products, priced from the same constants
    assert 'api_invoice_products(lang)' in handler
    assert "status=400" in handler
    # a Stars invoice link for the frontend to open with tg.openInvoice
    assert 'await bot.create_invoice_link(' in handler
    assert "currency='XTR'" in handler
    assert "provider_token=''" in handler
    assert 'LabeledPrice(' in handler


def test_select_route_applies_chat_rules():
    handler = MAIN[MAIN.index('async def _webapp_api_select('):MAIN.index('async def _start_web_server(')]
    assert 'validate_init_data' in handler
    # same gating as the in-chat character buttons
    assert "card.status not in ('active', 'premium')" in handler
    assert "card.status == 'premium' and not is_premium(telegram_id)" in handler
    assert "status=403" in handler
    assert 'set_user_character(telegram_id, character_id)' in handler
    assert "metadata={'character_id': character_id, 'source': 'webapp'}" in handler
    # the response re-renders the grid with the new selection
    assert 'api_characters(telegram_id)' in handler


def test_routes_registered():
    routes = MAIN[MAIN.index('async def _start_web_server('):MAIN.index('async def main():')]
    assert "add_post('/webapp/api/invoice', _webapp_api_invoice)" in routes
    assert "add_post('/webapp/api/select', _webapp_api_select)" in routes


def test_photo_pack_payment_flow():
    # pre_checkout validates the amount, successful_payment grants +1 credit
    # through the exact same record path as a chat photo purchase.
    pre = MAIN[MAIN.index('@dp.pre_checkout_query()'):MAIN.index('@dp.message(F.successful_payment)')]
    assert "elif payload=='photo_pack':" in pre
    assert 'ok=amount==PHOTO_COST_STARS' in pre

    pay = MAIN[MAIN.index('@dp.message(F.successful_payment)'):]
    photo_pack = pay[pay.index("if payload == 'photo_pack':"):pay.index("if payload == 'premium_month':")]
    assert "record_payment(message.from_user.id, 'photo', payment.total_amount, charge)" in photo_pack
    assert "'source': 'webapp'" in photo_pack


def test_characters_endpoint_knows_selection():
    handler = MAIN[MAIN.index('async def _webapp_api_characters('):MAIN.index('async def _webapp_api_shop(')]
    assert 'init_data' in handler
    assert 'api_characters(telegram_id)' in handler


def test_frontend_buys_and_selects():
    # tg.openInvoice with the backend-issued link
    assert 'tg.openInvoice(j.link' in INDEX
    assert "/webapp/api/invoice?init_data=" in INDEX
    assert "JSON.stringify({ product: productId })" in INDEX
    # purchase squares driven by the backend purchase list — V3.43.0: the
    # Come Closer pack grid; a tap opens the pay-method modal (Stars/SBP/crypto)
    assert 'class="pack" data-pay="${esc(x.id)}"' in INDEX
    assert 'openPay(b.dataset.pay)' in INDEX
    assert "s.purchases || []" in INDEX
    # character selection posts to the validated endpoint and re-renders
    # V3.35.0: the card tap opens the dialog; selection lives on the chat header
    assert "/webapp/api/select?init_data=" in INDEX
    assert "JSON.stringify({ character_id: c.id })" in INDEX
    assert 'openCharacter(el)' in INDEX
    assert 'renderCharacters(j.characters)' in INDEX
    # every dynamic string still goes through esc() or textContent
    assert 'data-name="${esc(c.name)}"' in INDEX
    assert 'el.textContent = text;' in INDEX
    # post-payment refresh of all tabs
    assert 'loadMe(); loadShop(); loadCharacters();' in INDEX


def test_no_unescaped_backend_strings_in_templates():
    # dynamic values inside template literals must be esc()-wrapped, or be one
    # of the known numeric/int expressions (Stars prices, counters, percents)
    numeric_ok = {
        'p.stars', 'p.rub', 'premBuy.stars', 'premBuy.rub', 'premWeek.stars', 'premWeek.rub',
        'credit.stars', 'i.stars', 'lvlPct', 'WIZ.stars', 'WIZ.rub', 'WIZ.usd',
        # V3.43.0: pack-square Stars price — numeric from config constants.
        'x.stars',
        # V3.43.0: the channel-bonus L-functions interpolate the peach amount
        # (a config integer) into their localized template.
        'b',
        's.free_tier.messages_per_day', 's.free_tier.photos_level_1_2',
        's.free_tier.photos_level_3_6',
        # V3.37.0: partner tab percent — always numeric from config, and the
        # interpolated L-string is esc()-wrapped at the render site anyway.
        'pct', 'min',
    }
    # These backend values sit outside esc() only because they flow into
    # textContent (checkword line, V3.39.0 character-page title/meta), not
    # innerHTML — so no HTML parsing ever happens on them.
    text_content_ok = {'d.check_word', 'el.dataset.name', 'L.selected_toast', 'c.name', 'c.age'}
    for m in re.finditer(r'\$\{([^}]+)\}', INDEX):
        expr = m.group(1).strip()
        if (expr.startswith('esc(') or expr in numeric_ok or expr.startswith('L.')
                or expr in text_content_ok or expr in (
            'badge', 'viewsBadge',
            'c.selected ? `<span class="badge" style="left:8px;top:auto;bottom:8px;color:#e8447f">❤️</span>` : \'\'',
            'heroBtn', 'heroWeekBtn', 'moRub', 'wkRub', 'creditRow', 'items', 'feats', 'price',
            # V3.43.0: the pack grid + pay-modal row fragments — every inner
            # backend field (id/emoji/title/rub) is esc()'d at build time.
            'packs', "rows.join('')",
            # V3.43.1: the pack discount badge fragment — esc()'d inside.
            'packBadge(x)',
            # V3.43.1: the living-tile media fragment — esc()'d inside.
            'cardMedia(c)',
            # V3.43.0: the auth-failure fragment — built from L constants and
            # static markup only, no backend strings inside.
            'authErrHtml()', 'msg',
            'customBadge', 'opts', 'review', 't',
            "role === 'user' ? 'user' : 'bot'",
            "c.custom ? '1' : '0'",
            "WIZ.params[step.key] === o.value ? ' sel' : ''",
            "WIZ.name ? '' : 'disabled'",
            # V3.36.0: the fiat formatter esc()-wraps its own fields internally
            'fiat(credit)', 'fiat(i)', 'fiat(p)',
            # V3.37.0: partner withdraw button state — a boolean ternary that
            # can only ever be '' or 'disabled', never backend data.
            "canWithdraw ? '' : 'disabled'",
            # V3.37.0: locally-built HTML fragments (every inner field esc()'d).
            'withdrawBtn', 'faq',
            # V3.38.0: scenario-hook line under the character name — built
            # from esc(c.hook) inside the fragment itself.
            'hookLine',
            # V3.38.0: the client's OWN Telegram initData, URL-encoded into an
            # <img> query string — never backend output (same value already
            # rides in every fetch URL).
            "encodeURIComponent(tg.initData || '')",
            # V3.38.0: locally-built «мои персонажи» fragment — every inner
            # field (photo/name/id/open_chat) is esc()'d at build time.
            'myCharsHtml',
            # V3.39.0: chatBubble's locally-computed role class — the ternary
            # can only ever be 'user' or 'bot', never backend data.
            'cls',
            # V3.39.0: chatBubble's locally-built media/text fragment — every
            # inner value (content + media src) is esc()'d at build time.
            'body',
            # V3.39.0: character-page meta ternaries — one yields only the
            # L.prem/L.active localization constants (into textContent), the
            # other only the 'on'/'' thumbnail CSS class from a local map index.
            "status === 'premium' ? L.prem : L.active",
            "i === 0 ? 'on' : ''",
            # V3.43.5: style-tile class ternaries — PIC_STYLE is local client
            # state; the result can only ever be ' on' or ''.
            "PIC_STYLE === 'anime' ? ' on' : ''",
            "PIC_STYLE === 'realistic' ? ' on' : ''",
            "PIC_STYLE === 'fantasy' ? ' on' : ''",
            # V3.43.5: the drawn style icons — static local SVG constants,
            # no backend data inside.
            'STYLE_ICONS.anime', 'STYLE_ICONS.realistic', 'STYLE_ICONS.fantasy',
            # V3.43.5: the language-chip fragment (codes and names esc()'d
            # inside) and its local class ternary.
            'langChipsHtml', "code === LANG ? ' on' : ''",
            # V3.44.0: leaderboard medal — local ternary result (emoji or number).
            'medal',
        ) or expr.startswith('`') or 'esc(' in expr or expr == "c.selected ? ' selected' : ''"):
            continue
        raise AssertionError(f'unescaped template value: {expr!r} in INDEX')
