"""V3.47.0 static checks: the growth pack — viral share, source attribution,
referral bonus tiers and the affiliate leaderboard.

Owner decisions this release encodes:
- Viral share stamps a watermark with a ?start=src_share_<uid> link on the
  EXPORT copy only; the in-app view and the paid download stay clean.
- Source attribution is first-touch-wins: User.source_tag is written once and
  never overwritten by a later deep link.
- Referral bonus tiers (3/10/25 → 🍑 + Premium) are granted once each, guarded
  by a per-tier marker event written in the SAME transaction as the credit bump.
- A src_share_<uid> install BOTH tags the source and credits the sharer.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
REF = (ROOT / 'services' / 'referral_service.py').read_text(encoding='utf-8')
PART = (ROOT / 'services' / 'partner_service.py').read_text(encoding='utf-8')
ANAL = (ROOT / 'services' / 'analytics_service.py').read_text(encoding='utf-8')
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
WMS = (ROOT / 'services' / 'watermark_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


# ── source attribution ─────────────────────────────────────────────────────
def test_source_attribution_backend_wired():
    assert "source_tag: Mapped[str] = mapped_column(String(48), default=\"\")" in MODELS
    assert 'def parse_source_payload(args: str | None) -> tuple[str | None, int | None]:' in REF
    assert 'def set_source(telegram_id: int, source_tag: str) -> bool:' in REF
    # first touch wins: never overwrites an existing tag
    assert 'if not user or (user.source_tag or ""):' in REF
    # /start parses src_/src_share_ and credits the sharer as referrer
    assert 'source_tag, share_referrer = parse_source_payload(command.args)' in MAIN
    assert 'remember_referral(message.from_user.id, share_referrer)' in MAIN
    # admin snapshot exposes the source breakdown so a $100 buy-in is measurable
    assert "'sources': [[(tag or 'organic'), int(cnt)] for tag, cnt in src_rows]" in ANAL


# ── referral bonus tiers ───────────────────────────────────────────────────
def test_referral_bonus_tiers_ladder_and_grant():
    assert 'REFERRAL_BONUS_TIERS = _parse_referral_tiers(REFERRAL_BONUS_TIERS_RAW)' in CONFIG
    assert '"3:10:0,10:30:7,25:100:30"' in CONFIG
    assert 'def maybe_grant_referral_tiers(telegram_id: int) -> list[dict]:' in REF
    assert 'def referral_tier_progress(telegram_id: int) -> dict:' in REF
    # idempotent: a per-tier marker event guards the grant
    assert 'def _tier_marker_event(idx: int) -> str:' in REF
    assert 'if _tier_already_granted(uid, idx):' in REF
    # a conversion re-checks the ladder for the referrer
    assert 'maybe_grant_referral_tiers(referrer_telegram_id)' in REF


# ── affiliate leaderboard ──────────────────────────────────────────────────
def test_affiliate_leaderboard_present():
    assert 'def affiliate_leaderboard(limit: int = 10, period_days: int | None = 30) -> list[dict]:' in PART
    # merged into the Mini App partner payload and the bot /contest screen
    assert "partner_service.affiliate_leaderboard(limit=5, period_days=30)" in WEB
    assert "earners = _ps.affiliate_leaderboard(limit=5, period_days=30)" in MAIN
    assert "'top_earners': top_earners," in WEB


# ── viral share + watermark ────────────────────────────────────────────────
def test_watermark_and_share_route():
    assert 'def apply_share_watermark(' in WMS
    assert 'src_share_' in WMS
    assert 'def share_image_bytes(telegram_id: int, image_id: int) -> bytes | None:' in WEB
    assert "'share_url': f\"/webapp/gallery/share/{row['id']}\"" in WEB
    assert 'async def _webapp_gallery_share(request: web.Request) -> web.Response:' in MAIN
    assert "app.router.add_get('/webapp/gallery/share/{image_id}', _webapp_gallery_share)" in MAIN


# ── Mini App surface (share button, referral CTA, invite link) ─────────────
def test_webapp_share_and_cta():
    assert "function sharePhotoImage(shareUrl) {" in INDEX
    assert "async function inviteFriends() {" in INDEX
    assert "me['invite'] = share_link(_me_bot.username or 'bot', telegram_id)" in MAIN
    assert "data['invite'] = share_link(me.username or 'bot', telegram_id)" in MAIN
    # the post-generation referral CTA lives on the delivered media
    assert 'class="gencta"' in INDEX
    assert "_gc[_gc.length - 1].addEventListener('click', inviteFriends)" in INDEX
    # gallery share tiles
    assert "class=\"galshare\"" in INDEX
