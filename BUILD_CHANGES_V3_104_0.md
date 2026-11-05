# V3.104.0 — keep and renew the people who paid

Data: only 3 people paid (397 ₽, Platega) and every one left the same or the next day. They got one
system line «Premium активирован» and nothing else; the week had no goodbye at all.

Every feature has its own env flag (default on). No pressure, no guilt, no fake scarcity.

1. **After the payment** (`services/paid_welcome.py`, `main._after_premium_paid`, Stars + Platega):
   a «✨ Вот что теперь открыто» card (unlimited chat, levels 1–10, 🌶 Пошлый режим, 🎭 Фетиши, private
   photos / «Раздеть», «Оживить» 2/day + circles, voice) with buttons «💬 открыть наш чат» and
   «🌶 Пошлый режим»; ~20 s later she writes herself (LLM, from memory; never mentions money or the
   subscription; fixed line if the LLM fails). Flags: `PAID_WELCOME_ENABLED`,
   `PAID_WELCOME_DELAY_SECONDS` (20).
   **Next day**: 18–40 h after the payment, 09–23 MSK, if he has not been here for 3 h, she writes first
   about something he told her. Once per payment. Flags: `PAID_DAY1_ENABLED`, `PAID_DAY1_MIN_HOURS`,
   `PAID_DAY1_MAX_HOURS`, `PAID_DAY1_SKIP_IF_ACTIVE_HOURS`. Events: `paid_welcome_card`,
   `paid_welcome_sent`, `paid_day1_sent`.
2. **Loyalty month** (`services/vip_offer.py`): his FIRST payment (trial or week) opens the existing
   −50% month (`premium_month_vip`, 349 ₽ / 250 ⭐) for as long as his paid days run + 48 h; it works
   while he is Premium (the month stacks on top). Buying a month/quarter closes it. Shown quietly under
   the welcome card, in the trial goodbye and in the renewal message. Flags: `LOYAL_OFFER_ENABLED`,
   `LOYAL_OFFER_GRACE_HOURS`. Event: `loyal_offer_opened`.
   **Before the end** (`services/renewal_care.py`): week / month / quarter (not the trial — it has
   `trial_followup`): in the last 24 h she recalls a concrete moment of their talks and says she would be
   glad if he stays (buttons: loyalty month or month, week); one short warm line up to 30 h after the
   end if he did not renew. 09–23 MSK only. Flags: `RENEWAL_CARE_ENABLED`, `RENEWAL_CARE_ENDED_ENABLED`,
   `RENEWAL_CARE_SOON_HOURS`, `RENEWAL_CARE_ENDED_HOURS`, `RENEWAL_CARE_PRODUCTS`. Events:
   `renewal_soon_sent`, `renewal_ended_sent`, `renewal_care_sent`.
3. **«Память как подарок»** (`services/memory_gift.py`): when he comes back after ≥3 h, once per 20 h,
   she gets one concrete memory to bring up herself (plans/worries first, then work and close people,
   then tastes/jokes; never his name; not the same memory for 7 days; at least 4 h old). The memory
   extraction prompt now asks for his name, work, close people, worries and dated plans. Only the
   memory id is stored in the event. Flags: `MEMORY_GIFT_ENABLED` (also switches the extraction prompt
   back), `MEMORY_GIFT_GAP_HOURS`, `MEMORY_GIFT_COOLDOWN_HOURS`, `MEMORY_GIFT_REPEAT_DAYS`,
   `MEMORY_GIFT_MIN_AGE_HOURS`. Event: `memory_gift_used`.

`/week` report shows the new events. Tests: `tests/test_v3104_paid_retention.py` (11). Full suite: same
16 baseline failures as main (missing assets), no new ones.
