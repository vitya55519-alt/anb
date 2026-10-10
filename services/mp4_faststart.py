"""V3.57.9: pure-Python MP4 «faststart» (move the moov atom before mdat).

Several storefront tiles were rendered with the index (moov) at the end of
the file, so a phone had to fetch the tail of a 2-3 MB clip before the first
frame could play. This is the qt-faststart algorithm: reorder the top-level
atoms and shift every chunk offset (stco / co64) by the size of moov.
No ffmpeg needed. Anything unexpected → returns None and the file is left as is.
"""
from __future__ import annotations

import logging
import os
import struct
from pathlib import Path

logger = logging.getLogger(__name__)

_CONTAINERS = {b'moov', b'trak', b'mdia', b'minf', b'stbl', b'edts', b'dinf', b'udta', b'mvex'}


def _top_atoms(data: bytes) -> list[tuple[bytes, int, int]] | None:
    atoms, pos, n = [], 0, len(data)
    while pos < n:
        if pos + 8 > n:
            return None
        size, kind = struct.unpack('>I4s', data[pos:pos + 8])
        if size == 1:
            if pos + 16 > n:
                return None
            size = struct.unpack('>Q', data[pos + 8:pos + 16])[0]
        elif size == 0:
            size = n - pos
        if size < 8 or pos + size > n:
            return None
        atoms.append((kind, pos, size))
        pos += size
    return atoms


def needs_faststart(data: bytes) -> bool:
    atoms = _top_atoms(data)
    if not atoms:
        return False
    kinds = [a[0] for a in atoms]
    return b'moov' in kinds and b'mdat' in kinds and kinds.index(b'moov') > kinds.index(b'mdat')


def _patch_offsets(moov: bytearray, delta: int) -> bool:
    def walk(start: int, end: int) -> bool:
        pos = start
        while pos + 8 <= end:
            size, kind = struct.unpack('>I4s', moov[pos:pos + 8])
            header = 8
            if size == 1:
                size = struct.unpack('>Q', moov[pos + 8:pos + 16])[0]
                header = 16
            if size < header or pos + size > end:
                return False
            body = pos + header
            if kind in _CONTAINERS:
                if not walk(body, pos + size):
                    return False
            elif kind == b'stco':
                count = struct.unpack('>I', moov[body + 4:body + 8])[0]
                for i in range(count):
                    o = body + 8 + i * 4
                    val = struct.unpack('>I', moov[o:o + 4])[0] + delta
                    if val > 0xFFFFFFFF:
                        return False
                    moov[o:o + 4] = struct.pack('>I', val)
            elif kind == b'co64':
                count = struct.unpack('>I', moov[body + 4:body + 8])[0]
                for i in range(count):
                    o = body + 8 + i * 8
                    moov[o:o + 8] = struct.pack('>Q', struct.unpack('>Q', moov[o:o + 8])[0] + delta)
            pos += size
        return True
    return walk(0, len(moov))


def faststart_bytes(data: bytes) -> bytes | None:
    """Return a moov-first copy of ``data``, or None if not needed / not safe."""
    try:
        if not needs_faststart(data):
            return None
        atoms = _top_atoms(data)
        moov_atom = next(a for a in atoms if a[0] == b'moov')
        moov = bytearray(data[moov_atom[1]:moov_atom[1] + moov_atom[2]])
        if b'cmov' in moov:  # compressed moov — leave it alone
            return None
        # Atoms that precede the first mdat stay in front (ftyp etc.); moov goes
        # right after them, so every byte from the first mdat on moves by len(moov).
        first_mdat = next(i for i, a in enumerate(atoms) if a[0] == b'mdat')
        head = [a for a in atoms[:first_mdat] if a[0] not in (b'free', b'skip')]
        tail = [a for a in atoms[first_mdat:] if a[0] != b'moov']
        removed_before_mdat = sum(a[2] for a in atoms[:first_mdat] if a[0] in (b'free', b'skip'))
        if not _patch_offsets(moov, len(moov) - removed_before_mdat):
            return None
        out = bytearray()
        for kind, pos, size in head:
            out += data[pos:pos + size]
        out += moov
        for kind, pos, size in tail:
            out += data[pos:pos + size]
        return bytes(out)
    except Exception as exc:  # never break serving over an optimisation
        logger.warning('faststart skipped: %s', exc)
        return None


def ensure_faststart(path: Path) -> bool:
    """Rewrite ``path`` in place (atomically) if its moov sits after mdat."""
    try:
        if path.suffix.lower() != '.mp4' or not path.is_file():
            return False
        data = path.read_bytes()
        fixed = faststart_bytes(data)
        if fixed is None:
            return False
        tmp = path.with_suffix('.mp4.tmp')
        tmp.write_bytes(fixed)
        os.replace(tmp, path)
        logger.info('faststart applied to %s (%d bytes)', path, len(fixed))
        return True
    except Exception as exc:
        logger.warning('faststart failed for %s: %s', path, exc)
        return False
