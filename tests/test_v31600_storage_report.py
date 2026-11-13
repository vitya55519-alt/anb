# V3.160.0 — рост базы перестаёт быть невидимым.
#
# Дамп 13.11: ночной бэкап весит десятки МБ, а фото и голос в него не кладутся
# намеренно. Итог: том Railway Hobby (~1 ГБ) может расти месяцами, и владелец
# узнаёт об этом только в день, когда запись упадёт. Поэтому к каждой ночной
# сводке прикладывается только чтение: размер базы, самые тяжёлые таблицы и
# сколько байтов живёт в LargeBinary-колонках — то, чего в Telegram-дампе нет.

import asyncio
import datetime as dt
import gzip
import json
from pathlib import Path

import config
from models.app_models import ProactivePhoto
from services import backup_service as B
from services.db import SessionLocal, engine
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
SCHED = (ROOT / 'services' / 'scheduler_service.py').read_text(encoding='utf-8')


def _add_a_pooled_photo() -> int:
    with SessionLocal() as s:
        row = ProactivePhoto(image_bytes=b'\xff' * 4096, content_type='image/jpeg',
                             kind='photo', character_id='storage_probe',
                             created_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
        s.add(row)
        s.commit()
        return row.id


def _pooled_rows() -> int:
    with SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(ProactivePhoto))


def test_human_bytes_reads_like_a_person():
    assert B.human_bytes(0) == '0 Б'
    assert B.human_bytes(None) == '0 Б'
    assert B.human_bytes(512) == '512 Б'
    assert B.human_bytes(2048) == '2.0 КБ'
    assert B.human_bytes(5 * 1024 * 1024) == '5.0 МБ'
    assert B.human_bytes(3 * 1024 ** 3 + 1024 * 1024) == '3.0 ГБ'


def test_report_names_the_binary_columns_and_weighs_them():
    _add_a_pooled_photo()
    before = _pooled_rows()
    rep = B.storage_report()
    assert rep['engine'] == engine.dialect.name
    assert 'proactive_photos.image_bytes' in rep['blob_columns']
    assert rep['blob_bytes'] >= 4096
    assert all(len(r) == 3 for r in rep['top'])
    assert 0 < len(rep['top']) <= 6
    weights = [-(r[2] or r[1]) for r in rep['top']]
    assert weights == sorted(weights)  # тяжёлые таблицы сверху
    assert _pooled_rows() == before    # только чтение: ни строчки не тронуто


def test_the_binary_columns_are_exactly_the_ones_the_dump_skips():
    # инвариант сводки: то, что storage_report считает байтами, обязано быть в
    # skipped дампа — иначе фраза «за спиной дампа живёт N картинок» врёт
    rep = B.storage_report()
    skipped = set()
    for raw in gzip.decompress(B.dump_database()[0]).splitlines():
        item = json.loads(raw)
        if isinstance(item, dict) and 'table' in item:
            skipped.update(f"{item['table']}.{c}" for c in item.get('skipped') or [])
    assert rep['blob_columns']
    assert set(rep['blob_columns']) == skipped


def test_summary_line_adds_the_disk_only_when_there_is_a_report():
    counts = {'users': 10, 'messages': 40}
    plain = B.summary_line(counts, 2 * 1024 * 1024)
    assert '💾' not in plain
    assert plain.startswith('🗄 бэкап базы: 2 таблиц, 50 строк, 2.0 МБ')

    storage = {'engine': 'postgresql', 'db_bytes': 700 * 1024 * 1024,
               'blob_bytes': 90 * 1024 * 1024,
               'blob_columns': ['proactive_photos.image_bytes', 'chat_media.data'],
               'top': [('proactive_photos', 120, 80 * 1024 * 1024),
                       ('chat_media', 30, 10 * 1024 * 1024),
                       ('users', 682, 0)]}
    with_disk = B.summary_line(counts, 2 * 1024 * 1024, storage)
    assert with_disk.startswith(plain)
    assert '💾 база целиком: 700.0 МБ' in with_disk
    assert '90.0 МБ картинок и голосов (2 колонок)' in with_disk
    assert 'proactive_photos 80.0 МБ' in with_disk
    assert 'users' not in with_disk.split('💾')[1]  # пустые таблицы не втягиваем
    assert len(with_disk) < 1000                    # лимит подписи Telegram

    empty = B.summary_line(counts, 1024, {'engine': 'sqlite', 'db_bytes': 0, 'blob_bytes': 0,
                                          'blob_columns': [], 'top': []})
    assert '💾 база целиком: 0 Б' in empty
    assert '(0 колонок)' in empty


def _fake_bot(sent):
    class Bot:
        async def send_document(self, chat_id, file, caption=None, **_kw):
            sent.append(('document', chat_id, caption))

        async def send_message(self, chat_id, text, **_kw):
            sent.append(('message', chat_id, text))
    return Bot()


async def _backup(bot):
    from services import scheduler_service
    await scheduler_service._db_backup(bot)


def test_a_broken_diagnostic_still_sends_the_backup(monkeypatch):
    sent = []
    monkeypatch.setattr(config, 'ADMIN_TELEGRAM_IDS', [771600001])

    def boom(*_a, **_kw):
        raise RuntimeError('volume full')

    monkeypatch.setattr(B, 'storage_report', boom)
    asyncio.run(_backup(_fake_bot(sent)))
    assert [s for s in sent if s[0] == 'document'], 'бэкап обязан уйти несмотря на диагностику'
    assert '💾' not in sent[0][2]


def test_backup_caption_carries_the_disk_when_the_report_works(monkeypatch):
    sent = []
    monkeypatch.setattr(config, 'ADMIN_TELEGRAM_IDS', [771600002])
    _add_a_pooled_photo()
    asyncio.run(_backup(_fake_bot(sent)))
    caption = next(s for s in sent if s[0] == 'document')[2]
    assert '💾 база целиком' in caption
    assert 'картинок и голосов' in caption


def test_the_diagnostic_sits_outside_the_dump_try():
    # диагностике нельзя лежать в том же try, что и дамп: иначе её падение
    # отменит бэкап — единственное, что реально защищает деньги и диалоги
    rail = SCHED[SCHED.index('async def _db_backup'):SCHED.index('def start_scheduler')]
    assert rail.index('dump_database') < rail.index('storage_report') < rail.index('summary_line')
    assert 'try:' in rail[:rail.index('storage_report')]
    assert 'logger.exception' in rail
