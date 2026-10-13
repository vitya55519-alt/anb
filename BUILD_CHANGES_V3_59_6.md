# V3.59.6 — relationship status that actually sticks, for peaches

- **Bug:** «Замужем» was picked but she answered «свободна, как птица». The status sat in the middle of a long prompt and lost to 30 lines of history. It is now also repeated as a short reminder right before the user's message.
- **Paid:** default is «Свободна» (or the constructor's choice for a custom girl); every change costs `MARITAL_CHANGE_PEACHES` (5 🍑 by default, Railway-configurable, admin free). The app asks to confirm the price; with too few peaches it says so and opens the shop. Tapping the current status is free.
- **Look:** the five chips sit in one neat scrollable row with «смена · 5 🍑» next to the title; the «Как задумано» chip is gone.
