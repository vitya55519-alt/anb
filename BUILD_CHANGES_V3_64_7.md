# V3.64.7 — «Пошлый режим» on the main screen

- Characters tab: a «🔥 Пошлый режим» banner right under «Бесплатные 🍑 за подписку на канал», with a one-line description («без стеснения и запретных тем: открыто про секс, желания и фантазии») and an «вкл» pill when it is on.
- Tap opens an explainer: what changes, «только 18+ · фишка Premium»; the button is «Включить 🔥», «Выключить» or «Открыть с Premium ⭐» (→ shop).
- The banner and the Settings row share one `toggleSpicy()`.
- `/webapp/api/spicy`: enabling now also requires the 18+ confirmation (`adult_confirm`, 403); Premium is still required; disabling is always allowed. Explicit-content gating by level is unchanged.
