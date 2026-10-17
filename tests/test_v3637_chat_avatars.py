"""V3.63.7: her small photo beside each of her messages in the app chat (WhatsApp-style)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPA = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_every_bot_bubble_gets_her_avatar():
    i = SPA.index('function chatBubble(')
    body = SPA[i:SPA.index('function herAvatar()')]
    assert "const av = (cls === 'bot') ? herAvatar() : '';" in body
    assert "(av ? ' hav' : '')" in body


def test_avatar_uses_chat_photo_and_hides_on_error():
    i = SPA.index('function herAvatar()')
    body = SPA[i:i + 400]
    assert 'CHAT.duo' in body  # duo chats keep their per-line avatars
    assert "CHAT.photo || (CHAT.id ? '/webapp/photo/' + CHAT.id : '')" in body
    assert 'esc(src)' in body and "visibility" in body


def test_avatar_css_sits_left_of_bubble():
    assert '.msg.bot.hav { position: relative; margin-left: 36px;' in SPA
    assert '.msg .bav { position: absolute; left: -36px; bottom: 0;' in SPA
