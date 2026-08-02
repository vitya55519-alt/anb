# Photo engine V2

## What changed

- Anna can send a photo as part of a normal conversation. The bot no longer always asks the user to press a `Покажи` button when a photo moment appears.
- Direct requests such as `скинь фотку`, `селфи`, `покажи себя` trigger an automatic photo when the current relationship level allows it.
- Contextual mentions such as `ты сейчас в кафе?`, `что делаешь?`, `как одета?` can sometimes produce a photo naturally. The probability is controlled by `AUTO_PHOTO_PROBABILITY`.
- Automatic photos consume the same daily free-photo quota as manually requested photos, so the limit cannot be bypassed.
- `/photo` remains available for explicit manual selection.

## Daily limits

Default free-photo limits by relationship stage are:

1. stranger — 2/day
2. acquaintance — 3/day
3. close — 4/day
4. intimate — 5/day
5. deeply_connected — 6/day

Override with `PHOTO_DAILY_LIMITS` if desired.

## Keeping Anna's face consistent

Reference selection is scene-aware instead of always using the first reference:

- selfie/cafe/park/evening -> `01_face_front_white_top.png`
- mirror/outfit -> `02_full_body_white_top.png`
- home -> `04_lying_hair_down.png`
- personal -> `05_lying_hair_up.png`
- lingerie -> `06_front_black_lingerie.jpg`

The edit prompt explicitly treats facial identity as the highest-priority invariant and asks the image model to change only scene, pose, clothing, lighting and framing.

For best consistency keep all Anna reference images in `data/references/anna/` and use `IMAGE_REFERENCE_MODE=edit` to fail loudly if reference editing is unavailable.

## Owner testing

Set `ADMIN_TELEGRAM_IDS` to the numeric Telegram ID of the owner.

Commands:

- `/testlevel 1` — stranger
- `/testlevel 2` — acquaintance
- `/testlevel 3` — close
- `/testlevel 4` — intimate
- `/testlevel 5` — deeply connected
- `/testlevel status`
- `/testlevel off`

The test level is kept in memory and does not change the real relationship scores. It affects the chat tone, relationship-gated photo scenes and photo limits while testing.


## Identity/Conversation update

The photo layer now treats face, hair and body proportions as immutable identity attributes. Scene, clothing, pose, lighting and camera framing are variable. Normal users access photos through buttons and contextual conversation rather than needing commands. Creator testing supports six stages.
