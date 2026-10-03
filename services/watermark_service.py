"""V3.47.0: the viral share watermark.

A friend who receives a shared «Наедине» photo should be able to get the same
thing in one tap — so the copy that leaves the app carries a small burned-in
invite bar: a teaser line plus a ?start=src_share_<uid> deep link that both
tags the new install's source AND credits the sharer as their referrer (handled
in main.start). The watermark is applied ONLY to the exported share copy, never
to the in-app view or the paid full-resolution download, so paying users get a
clean image.

Everything here is best-effort: on any Pillow/decoding failure we hand back the
original bytes so a share never dead-ends because of a font or a corrupt frame.
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

# Candidate truetype paths (Debian/Railway, macOS, Windows) — the first that
# loads wins; otherwise Pillow's bundled scalable default is used.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
)


def _load_font(size: int):
    from PIL import ImageFont
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow: load_default takes no size
        return ImageFont.load_default()


def _invite_link(bot_username: str, telegram_id: int) -> str:
    bot = (bot_username or "").strip().lstrip("@") or "anna67901_bot"
    return f"t.me/{bot}?start=src_share_{int(telegram_id)}"


def apply_share_watermark(image_bytes: bytes, bot_username: str, telegram_id: int,
                          teaser: str = "хочешь так же? нажми и получи →") -> bytes:
    """Burn a translucent invite bar into the bottom of a JPEG/PNG byte stream.

    Returns the watermarked JPEG bytes, or the untouched original on any error
    (never raises — this sits on a user-facing share path).
    """
    if not image_bytes:
        return image_bytes
    try:
        from PIL import Image, ImageDraw

        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGBA")
        w, h = img.size
        if w < 64 or h < 64:
            return image_bytes

        bar_h = max(48, int(h * 0.12))
        link = _invite_link(bot_username, telegram_id)

        # Gradient-ish translucent panel so text stays legible over any outfit.
        overlay = Image.new("RGBA", (w, bar_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for row in range(bar_h):
            # fade from ~78% black at the very bottom to ~45% at the top
            alpha = int(115 + (185 - 115) * (row / max(1, bar_h - 1)))
            draw.rectangle([0, row, w, row], fill=(10, 6, 16, alpha))

        link_font = _load_font(max(16, int(bar_h * 0.30)))
        teaser_font = _load_font(max(13, int(bar_h * 0.24)))
        pad = max(6, int(w * 0.03))

        # Left-aligned teaser on top, right-aligned invite link under it.
        d = ImageDraw.Draw(overlay)
        lx0, ly0, lx1, ly1 = d.textbbox((0, 0), link, font=link_font)
        link_w = lx1 - lx0
        d.text((pad, int(bar_h * 0.10)), teaser, font=teaser_font,
               fill=(255, 200, 230, 255))
        d.text((max(pad, w - pad - link_w), int(bar_h * 0.52)), link,
               font=link_font, fill=(255, 255, 255, 255))

        img.alpha_composite(overlay, dest=(0, h - bar_h))
        out = img.convert("RGB")
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=88)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001 - best-effort on a share path
        logger.warning("share watermark skipped: %s", exc)
        return image_bytes
