"""V3.48.1 static checks: the storefront card media is persisted in PostgreSQL.

Owner pain that this release fixes: «я поменял медиа витрину … но после
редиплоя я вынужден менять каждый раз всё это — капец долго». The admin-set
showcase media (photo/gif/webp/mp4) shipped in V3.43.3 as a bare file under
``data/card_media/<id>/card_override.<ext>``. That folder lives on Railway's
ephemeral disk, so every redeploy wiped it and the owner had to re-upload every
character's card. The bytes now live in the ``card_overrides`` table (like
ChatMedia / PageGalleryShot / AchievementBadge already do); the disk file is only
a re-materializable cache.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
DB = (ROOT / 'services' / 'db.py').read_text(encoding='utf-8')


def test_card_override_model_and_registration():
    assert 'class CardOverride(Base):' in MODELS
    assert '__tablename__ = "card_overrides"' in MODELS
    # exactly one active override per character, mirroring the single disk file
    assert 'character_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)' in MODELS
    assert 'image_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)' in MODELS
    # registered so create_all builds the table on the prod DB at startup
    assert 'CardOverride' in DB


def test_set_card_override_writes_bytes_to_the_database():
    fn = WEB[WEB.index('def set_card_override('):WEB.index('def clear_card_override(')]
    assert 'from models.app_models import CardOverride, utcnow' in fn
    assert 'row.image_bytes = data' in fn
    assert 'row.ext = ext' in fn
    assert 's.commit()' in fn
    # the disk cache is still mirrored for immediate grid serving
    assert 'target.write_bytes(data)' in fn


def test_character_card_override_rematerializes_from_db_on_disk_miss():
    fn = WEB[WEB.index('def character_card_override('):WEB.index('def set_card_override(')]
    # returns the cached file when present ...
    assert 'if item.exists():' in fn
    # ... and restores it from PostgreSQL when the ephemeral disk was wiped
    assert 'row = s.scalar(select(CardOverride).where(CardOverride.character_id == character_id))' in fn
    assert "target = folder / f'card_override{row.ext}'" in fn
    assert 'target.write_bytes(row.image_bytes)' in fn
    assert "'card override db restore failed character=%s'" in fn


def test_clear_card_override_drops_the_database_row():
    fn = WEB[WEB.index('def clear_card_override('):WEB.index('# ── V3.47.4')]
    assert 'from models.app_models import CardOverride' in fn
    assert 'row = s.scalar(select(CardOverride).where(CardOverride.character_id == character_id))' in fn
    assert 's.delete(row)' in fn
    assert "'card override db delete failed character=%s'" in fn


def test_public_service_signatures_are_unchanged():
    # the V3.43.3 static pins still hold — only the storage layer moved under them
    assert 'def character_card_override(character_id: str) -> Path | None:' in WEB
    assert 'def set_card_override(character_id: str, data: bytes, ext: str) -> Path:' in WEB
    assert 'def clear_card_override(character_id: str) -> bool:' in WEB
    assert "return ROOT / 'data' / 'card_media' / character_id" in WEB
