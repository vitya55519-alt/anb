# V3.100.0 — care follow-up (services/care_followup.py)

Backup 2026-11-03, 106 people writing since 25 Oct: 45 ask for photos / explicit talk, 25 write
that they are tired, sad or unwell, 20 write about love or missing her.

- A message like «устал / мне грустно / мне плохо / bad day» makes her listen first: no flirting,
  no cliffhanger, no director hook in that reply, one soft question.
- A crisis phrase (wants to die, self-harm) gets a serious, calm reply that stays with him and
  points to a close person or a helpline (no invented numbers). Premium or not.
- Only the KIND of the mood (care/crisis) is stored (event `care_noted`, at most once per 20 h),
  never his words.
- Next morning (chat_service.morning_callback) she asks how he is today, ahead of the open-loop
  promise from V3.99.0. Events: care_noted, care_followup_sent, care_followup_sent_morning.
- Env CARE_FOLLOWUP_ENABLED=false turns it off.

Stacked on V3.99.0 (PR #118): merge that one first.
