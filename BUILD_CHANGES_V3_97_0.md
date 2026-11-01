# V3.97.0 — growth pack after the 1 Nov 2026 stats review

Stats (backup 2026-11-01 00:30): 534 users, D1 8%, two 99 ₽ trials and no renewals,
9 users with 177–525 messages hit the daily limit up to 387 times and never paid,
«хм… я зависла на секунду 🙈» went out 141 times in a week.

- Dialogue: an EMPTY MiniMax answer (reasoning ate the cap) is retried once with
  more room before Gemini; `dialogue` gets 1024 reasoning headroom up front
  (env MINIMAX_DIALOGUE_HEADROOM, MINIMAX_EMPTY_RETRY_HEADROOM). If everything is
  empty she answers with a varied live «busy» line (ru/en) instead of the frozen one.
- Voice: SPEAK_FREE_PER_DAY (default 3) free «🔊» listens a day without Premium,
  the app toasts how many are left; the Premium sheet comes after.
- Trial 99 ₽: also on the bot's «she fell asleep» wall; chat chips (sext offer,
  photo blocks) name the trial with its price and open the trial-first sheet.
- VIP −50% month (services/vip_offer.py): after the 3rd limit hit, a one-time
  48 h window, Stars (`premium_month_vip`, buy:premium_vip) and card/SBP; app
  limit answer carries `vip`, the sheet puts it first. Env VIP_OFFER_*.
- Trial follow-up (services/trial_followup.py, every 15 min): she writes in the
  last 20 h of a trial and once within 30 h after it ended, with week/month buttons.
- Morning ritual continues yesterday's talk (chat_service.morning_callback) when
  he wrote in the last 36 h.
- First minutes (services/first_minutes.py, every 3 min): one nudge 10 min after
  /start — the 18+ step, or a shy «скажи хотя бы привет» if he never wrote.
- Weekly report to admins Monday 09:00 MSK and /week (services/weekly_report.py);
  app messages to «Девушка дня» are tagged `girlday` in analytics.
