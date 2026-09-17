# AnnaBot V3.42.2 — Chat Strip: Voice Button Removed, Actions Get Readable Labels

## Owner request
«убери кнопочку из чата, связанную с голосом … он работает криво» and «там
маленькие кнопочки, кривые, они непонятно для чего сделаны … человек, который
заходит, он вообще не понимает, зачем это все» (screenshot of the in-app chat
action strip).

## Voice action removed from the chat
- The `🎙` button (`#mediaVoice`) and its `requestMedia('voice')` click listener are gone from the Mini App chat strip — the owner reports it renders crookedly.
- Backend voice support and the `<audio>` bubble for already-stored voice messages stay, so history still plays; only the broken entry point is removed.

## The strip is now self-explanatory
- Each remaining action is a **labeled pill**: an icon on top and a small localized text label under it (`.chat-media button .ic` / `.lb`), replacing the cryptic 38×38 icon-only squares.
- Labels (RU / EN) come from the `L` dictionary and are applied at localize time:
  📸 Фото/Photo · 🎬 Видео/Video · 🎥 Кружок/Circle · 🎯 Задание/Quest · 💕 Свидание/Date · 🏠 Квартира/Apartment.
- A newcomer can now read what every button does instead of guessing from an emoji.

## Ops
- Tests: `tests/test_v3422_chat_action_labels_static.py` (voice button + listener removed, label spans + localization wiring, pill CSS, RU/EN label strings); `test_v3390`/`test_v3410` updated to assert the voice button is gone; all 33 version pins bumped to 3.42.2.
