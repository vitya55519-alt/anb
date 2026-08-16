# V3.9 closed-beta checklist

1. Keep one Railway bot replica when using Telegram long polling.
2. Required existing variables: TELEGRAM_TOKEN, OPENAI_API_KEY, DATABASE_URL, FAL_KEY.
3. Recommended:
   - PHOTO_ROUTER_MODE=hybrid
   - PHOTO_SET_SIZE=3
   - FAL_MODEL=fal-ai/bytedance/seedream/v4.5/edit
4. Optional beta guardrails:
   - DAILY_IMAGE_BUDGET_USD
   - MONTHLY_IMAGE_BUDGET_USD
   - OPENAI_IMAGE_ESTIMATED_COST_USD
5. Test `/start` onboarding.
6. Test an OpenAI scene such as Park/Street and verify frames arrive one-by-one.
7. Test a Seedream scene and verify up to 3 sequential frames.
8. While a photo is generating, send a normal chat message: chat should remain responsive.
9. Press a photo button twice quickly: only one job should be created for that user.
10. Admin: `/stats` should show telemetry after several events.
