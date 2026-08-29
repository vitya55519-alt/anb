# V3.26.1 — fake-photo interception and relaxed photo-accept regex

## Owner report

Screenshot: Anna offered «фотку скинуть тебе?», the user answered
«Давай буду рад )», and instead of a real photo the chat showed a raw
role-played placeholder `[фото: Anna дома вечером — чёрный топ, ...]`.

## Root causes

1. `_PHOTO_ACCEPT` was anchored `^...$` (single word only), so
   «давай буду рад )» never counted as acceptance and the real photo flow
   did not start; the message fell through to the chat model.
2. The chat model then "sent" the photo by writing `[фото: ...]` in plain
   text, and nothing stripped it before delivery.

## Fixes in `main.py`

- `_PHOTO_ACCEPT` is now prefix + word boundary (`\b` instead of `$`), so
  «давай буду рад )», «yes please», «давай, покажи» all count. A «нет»
  guard at the call site keeps «да нет» / «давай не надо» from triggering.
- New `_FAKE_PHOTO_BLOCK` + `_strip_fake_photo`: bracketed `[фото: ...]` /
  `[photo: ...]` blocks are stripped from every text and voice reply.
- New `_deliver_intercepted_photo` + shared `_photo_accept_flow`: when the
  model role-plays sending a photo, a real one is delivered instead (free
  daily photo, or the cheap Stars offer when the limit is spent). The
  accept branch reuses the same helper — no duplicated invoice code.

## Fix in `services/character_service.py`

System prompt ФОТО section now explicitly forbids the model from writing
`[фото: ...]` / `[photo: ...]` or any square-bracket simulation — the
system delivers photos as separate messages.

## Tests

`tests/test_v3261_fake_photo_accept_static.py` — 5 tests. The regexes are
extracted from main.py via AST constant reading (no eval). Suite: 371.
