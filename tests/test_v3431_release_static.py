"""V3.43.1 static pins: photo-engine fixes, the peach pack ladder, living tiles.

1. Studio pictures work again: Seedream t2i routes to the dedicated
   text-to-image endpoint (the edit endpoint 422s on empty ``image_urls``),
   and the Gemini image leg retries a 429 quota burst twice with backoff.
2. The peach pack ladder (10/30/100 credits, −10%/−25%) replaces the single
   photo-credit square in every payment chain: Stars pre_checkout /
   successful_payment, FreeKassa notify, Wallet Pay webhook, the pay modal.
3. Storefront tiles: the Ken-Burns «гифка» re-renders from the CURRENT
   canonical references, and an admin job renders i2v living tiles
   (smile + air kiss) served as muted mp4 loops in the grid.
4. UI polish: a bigger channel-subscribe banner and like button, and the
   confusing «СЮЖЕТ» caption now reads «КАК ВЫ ПОЗНАКОМИТЕСЬ».
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
PAYMENTS = (ROOT / 'services' / 'payments.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()


def test_version_bumped():
    assert VERSION in ('3.44.3', '3.43.7', '3.43.6', '3.43.5', '3.43.4', '3.43.3', '3.43.2', '3.43.1')


# ── 1. photo engines: t2i endpoint + 429 backoff ────────────────────────────

def test_seedream_t2i_uses_the_text_to_image_endpoint():
    # the edit endpoint validates image_urls as a non-empty sequence and
    # answered HTTP 422 to every reference-free studio prompt.
    assert 'FAL_MODEL_T2I = os.getenv("FAL_MODEL_T2I", "fal-ai/bytedance/seedream/v4.5/text-to-image")' in CONFIG
    assert 'model=FAL_MODEL_T2I' in PHOTO
    # V3.44.3: retired routes fall back to known alternates on 404
    assert "endpoint = f\"https://fal.run/{candidate}\"" in PHOTO
    assert "if response.status_code == 404 and candidate != candidates[-1]:" in PHOTO
    # an empty reference list no longer ships in the payload at all
    assert "payload['image_urls'] = image_urls" in PHOTO
    assert "'image_urls': image_urls," not in PHOTO


def test_gemini_image_retries_quota_bursts_twice():
    fn = PHOTO[PHOTO.index('async def _gemini_image_one_frame'):PHOTO.index('async def _run_gemini_set')]
    assert 'for attempt in range(3):' in fn
    assert 'if response.status_code in retryable_statuses and attempt < 2:' in fn
    assert 'await asyncio.sleep(2.0 * (attempt + 1))' in fn


# ── 2. the peach pack ladder ────────────────────────────────────────────────

def test_pack_prices_and_grants():
    assert 'PEACH_PACK_10_STARS = int(os.getenv("PEACH_PACK_10_STARS", str(PHOTO_COST_STARS * 10)))' in CONFIG
    assert 'PEACH_PACK_30_STARS = int(os.getenv("PEACH_PACK_30_STARS", str(int(PHOTO_COST_STARS * 30 * 0.9))))' in CONFIG
    assert 'PEACH_PACK_100_STARS = int(os.getenv("PEACH_PACK_100_STARS", str(int(PHOTO_COST_STARS * 100 * 0.75))))' in CONFIG
    assert 'PEACH_PACK_CREDITS = {"peach_pack_10": 10, "peach_pack_30": 30, "peach_pack_100": 100}' in CONFIG
    # payments: priced in PRODUCTS, granted in one go
    assert '"peach_pack_10":PEACH_PACK_10_STARS' in PAYMENTS
    assert 'user.photo_credits=(user.photo_credits or 0)+PEACH_PACK_CREDITS[product]' in PAYMENTS


def test_pack_stars_chain():
    pre = MAIN[MAIN.index('@dp.pre_checkout_query()'):MAIN.index('@dp.message(F.successful_payment)')]
    assert 'elif payload in PEACH_PACK_STARS:' in pre
    assert 'ok=amount==PEACH_PACK_STARS[payload]' in pre
    pay = MAIN[MAIN.index('@dp.message(F.successful_payment)'):]
    pack = pay[pay.index('if payload in PEACH_PACK_STARS:'):pay.index("if payload == 'photo_pack':")]
    assert 'record_payment(message.from_user.id, payload, payment.total_amount, charge)' in pack
    assert 'pack_n = PEACH_PACK_CREDITS[payload]' in pack


def test_pack_fiat_and_notify_chains():
    fk = MAIN[MAIN.index('def _fk_amount_for('):MAIN.index("@dp.callback_query(F.data.startswith('fkapi:'))")]
    assert 'if product in PEACH_PACK_STARS:' in fk
    assert 'return fiat_values(PEACH_PACK_STARS[product])[0]' in fk
    notify = MAIN[MAIN.index('async def _fk_notify'):]
    notify = notify[notify.index("elif product == 'photo':"):notify.index('else:')]
    assert 'elif product in PEACH_PACK_CREDITS:' in notify
    link = MAIN[MAIN.index('async def _webapp_api_pay_link('):MAIN.index('async def _webapp_api_select(')]
    assert 'if not fk_product and product_id in PEACH_PACK_STARS:' in link


def test_pack_squares_and_badges():
    assert "'id': 'peach_pack_100'" in WEBAPP_SVC
    assert "'payload': 'peach_pack_30'" in WEBAPP_SVC
    assert "'badge': '−25%'" in WEBAPP_SVC
    assert '100 персиков' in WEBAPP_SVC and '100 peaches' in WEBAPP_SVC
    # frontend: the discount corner badge + the pay modal reuse the grid
    assert 'const packBadge = x => x.badge' in INDEX
    assert '.pack .bdg {' in INDEX
    assert '${packBadge(x)}' in INDEX


# ── 3. storefront tiles: fresh Ken-Burns + i2v living loops ─────────────────

def test_tiles_rebuild_from_current_canonicals():
    assert 'def rebuild_card_tile(character_id: str) -> Path | None:' in WEBAPP_SVC
    assert "sources = sorted(folder.glob('01_*look*.png')) or sorted(folder.glob('00_*face*.png'))" in WEBAPP_SVC
    assert 'width, height, frames = 300, 400, 16' in WEBAPP_SVC
    assert "@dp.message(Command('retiles'))" in MAIN


def test_living_tiles_job_and_route():
    assert 'LIVE_TILE_PROMPT = (' in MAIN
    assert 'blows a playful air kiss' in MAIN
    assert 'async def _run_live_tiles(admin_id: int) -> None:' in MAIN
    assert "@dp.message(Command('livetiles'))" in MAIN
    assert 'webapp_service.write_card_live(cid, video_bytes)' in MAIN
    assert 'def character_card_live(character_id: str) -> Path | None:' in WEBAPP_SVC
    assert 'def canonical_face_bytes(character_id: str, max_side: int = 768) -> bytes | None:' in WEBAPP_SVC
    assert 'def write_card_live(character_id: str, video_bytes: bytes) -> Path | None:' in WEBAPP_SVC
    assert 'def builtin_character_ids() -> tuple[str, ...]:' in WEBAPP_SVC
    assert "add_get('/webapp/live/{character_id}', _webapp_live)" in MAIN
    assert "content_type='video/mp4'" in MAIN
    # the grid plays the loop when rendered, else the Ken-Burns webp
    assert "'live': (f'/webapp/card/{card.character_id}?v={ver}'" in WEBAPP_SVC
    assert 'const cardMedia = c => c.live' in INDEX
    assert '.card .photo video {' in INDEX


# ── 4. UI polish ────────────────────────────────────────────────────────────

def test_ui_polish_pins():
    # the channel-subscribe banner grew (owner: «кнопку за подписку больше»)
    assert 'margin: 12px 4px 4px; padding: 15px 16px; border: 0; border-radius: 16px;' in INDEX
    assert 'width: 46px; height: 46px; border-radius: 50%; flex: 0 0 auto;' in INDEX
    # the like button is thumb-sized now
    assert 'background: rgba(10,5,14,.7); color: #fff; font-size: 20px; font-weight: 700; padding: 12px 20px; cursor: pointer;' in INDEX
    assert 'backdrop-filter: blur(6px); box-shadow: 0 2px 12px rgba(0,0,0,.35);' in INDEX
    # the plot block speaks human
    assert "plot: 'ОНА ПИШЕТ ТЕБЕ ПЕРВОЙ'" in INDEX
    assert "plot: 'SHE MESSAGES YOU FIRST'" in INDEX
