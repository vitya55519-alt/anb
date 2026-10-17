# V3.62.15 — bot profile from code

- On startup the bot sets its display name, short description (profile/share card) and description (empty chat before «Запустить») for RU and EN, writing each only when it differs. Name overridable via BOT_DISPLAY_NAME / BOT_DISPLAY_NAME_EN; BOT_PROFILE_ENABLED=0 turns it off.
