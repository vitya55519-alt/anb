"""V3.47.2/3 static checks: the morning/evening ritual MEDIA pool and the
new-user unlimited-text activation window.

Owner decisions these releases encode:
- The admin uploads ~20 varied media into a pool; a ritual picks one at random
  so a proactive ping lands as real content from the character, no watermark.
- V3.47.3: the pool is not photos only — GIFs (animation) and short videos are
  accepted too, stored with a 'kind' and sent back with the matching method.
- New users get unlimited TEXT messages for the first 24 hours after
  registration; the Mini App chats tab shows a live «осталось HH:MM:SS» banner.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')
RFS = (ROOT / 'services' / 'retention_features_service.py').read_text(encoding='utf-8')
ACCESS = (ROOT / 'services' / 'access_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


# ── storage: DB-backed media pool with a kind column ───────────────────────
def test_proactive_media_model_and_registration():
    assert 'class ProactivePhoto(Base):' in MODELS
    assert '__tablename__ = "proactive_photos"' in MODELS
    # V3.47.3: 'photo' | 'gif' | 'video' rides next to the bytes
    assert "kind: Mapped[str] = mapped_column(String(8), default=\"photo\")" in MODELS
    assert 'ProactivePhoto' in DB  # create_all/auto-migrate sees it


# ── service CRUD: per-kind limits, kind-aware list and random pick ─────────
def test_pool_service_is_kind_aware():
    assert "PROACTIVE_MEDIA_KINDS = ('photo', 'gif', 'video')" in RFS
    assert 'def proactive_max_bytes(kind: str) -> int:' in RFS
    assert "def add_proactive_photo(data: bytes, content_type: str = 'image/jpeg', kind: str = 'photo'," in RFS
    assert "character_id: str | None = None) -> bool:" in RFS  # V3.56.7 per-character pool
    assert "if len(data) > proactive_max_bytes(kind):" in RFS
    assert "'kind': getattr(r, 'kind', None) or 'photo'," in RFS
    # the random pick reports the kind so the sender can route by it
    assert "return row.image_bytes, (row.content_type or 'image/jpeg'), (getattr(row, 'kind', None) or 'photo')" in RFS


# ── delivery: the ritual sends photo / GIF / video by kind ─────────────────
def test_ritual_sends_media_by_kind():
    ritual = SCHED[SCHED.index('async def _rituals(bot):'):SCHED.index('async def _donation_reminder(bot):')]
    assert 'shot = retention_features_service.random_proactive_photo(char_id)' in ritual
    assert "data, ctype, kind = shot" in ritual
    assert 'await bot.send_animation(int(tg_id), BufferedInputFile(data, filename=\'ritual.mp4\'), caption=text)' in ritual
    assert 'await bot.send_video(int(tg_id), BufferedInputFile(data, filename=\'ritual.mp4\'), caption=text)' in ritual
    assert 'await bot.send_photo(int(tg_id), BufferedInputFile(data, filename=\'ritual.jpg\'), caption=text)' in ritual
    # empty pool keeps the old plain-text behavior
    assert 'await bot.send_message(int(tg_id),text)' in ritual


# ── admin upload: photo OR animation OR video lands in the pool ────────────
def test_admin_pool_upload_accepts_all_media():
    assert "@dp.message(lambda m: m.from_user is not None and m.from_user.id in PROPHOTO_WAIT,\n            (F.photo | F.animation | F.video))" in MAIN
    upload = MAIN[MAIN.index('async def admin_prophoto_upload('):MAIN.index('def _admin_gender_keyboard(')]
    assert "file, kind, ctype = message.animation, 'gif', (message.animation.mime_type or 'video/mp4')" in upload
    assert "file, kind, ctype = message.video, 'video', (message.video.mime_type or 'video/mp4')" in upload
    assert 'limit = rfs.proactive_max_bytes(kind)' in upload
    assert 'ok = rfs.add_proactive_photo(buf.getvalue(), ctype, kind,' in upload
    assert 'character_id=PROPHOTO_WAIT.get(message.from_user.id))' in upload  # V3.56.7
    # admin surface mentions all three media kinds
    assert "callback_data='admin:prophoto'" in MAIN
    assert '➕ Добавить фото / GIF / видео' in MAIN
    assert "_PROPHOTO_KIND_EMOJI = {'photo': '📸', 'gif': '🎞', 'video': '🎬'}" in MAIN


# ── 24h unlimited text for new users (text only — media stays gated) ───────
def test_new_user_unlimited_text_window():
    assert 'NEW_USER_UNLIMITED_HOURS = max(0, int(os.getenv("NEW_USER_UNLIMITED_HOURS", "24")))' in CONFIG
    gate = ACCESS[ACCESS.index('def can_send_message'):ACCESS.index('def unlimited_text_remaining')]
    assert 'if NEW_USER_UNLIMITED_HOURS and user.created_at:' in gate
    assert 'def unlimited_text_remaining(telegram_id:int)->int:' in ACCESS
    # api_me exposes the remaining seconds for the banner
    assert "me['unlimited_remaining'] = unlimited_text_remaining(telegram_id)" in MAIN


# ── Mini App banner: markup, styles, live countdown, i18n ─────────────────
def test_webapp_unlimited_banner():
    assert 'id="unlimBanner" class="unlim"' in INDEX
    assert '.unlim { display: flex;' in INDEX
    assert 'function renderUnlimitedBanner()' in INDEX
    assert 'function _fmtHMS(sec)' in INDEX
    assert 'setInterval(_unlimTick, 1000);' in INDEX
    assert 'renderUnlimitedBanner();' in INDEX[INDEX.index('async function loadMe()'):]
    # both languages carry the labels
    assert INDEX.count("unlim_title:") == 2
    assert INDEX.count("unlim_sub:") == 2
    assert INDEX.count("unlim_left:") == 2
