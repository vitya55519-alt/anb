# AnnaBot V3.10.5 — Photo Reliability + Library Rescue

- Ordinary GPT Image 2 path now uses a fully-clothed body-silhouette reference instead of the revealing canonical artwork.
- Body identity wording is neutral and ratio-based to preserve proportions without unnecessarily increasing input-moderation risk.
- Added a true AI-failure -> Telegram Library rescue path for free ordinary photos.
- Rescue first prefers the requested scene, then compatible unlocked ordinary scenes, then other unlocked ordinary library scenes.
- Rescue respects cumulative relationship level (pack level <= current level), unseen-first rotation, and never falls into private/lingerie scenes.
- A successful rescue counts as the user's free photo request; a total failure still does not consume quota.
- Existing exact-scene library-first routing remains unchanged.
