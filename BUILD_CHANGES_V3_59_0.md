# V3.59.0 — engagement basics

- **Honest D1/D7.** Retention counted only text typed in the bot chat; Mini App chats, dates, stories and app opens were invisible, so D1 read ≈1%. Now any user-started action counts (`ACTIVE_EVENTS`); bot-sent pushes do not.
- **Day-0 funnel** in both stats screens: /start → 18+ → first own message (30 days).
- **She writes first.** After the 18+ confirmation the user's girl sends a personal greeting that ends with a question (saved into the dialog so her memory has it). It is the last message in the chat, after the bonus line and the donation note.
- **Pushes from the right girl.** The «скучаю»/LLM nudges used the default heroine for everyone; now they use the user's selected character (state row, texts and LLM persona).
