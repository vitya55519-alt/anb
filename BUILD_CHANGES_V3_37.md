# AnnaBot V3.37.0 — Партнёрка 40%, Аниме-конструктор, Пошлый режим (Premium)

Owner request: «мне кажется партнерка сделана шикарно, сделай также и в нашем
боте, и партнерку и кнопки … хочется чтобы человек когда создавал персонажа
для всех пользователей, мог еще и аниме девушек создавать, пошлый режим
общения только с премиумом (сделай переключатель)».

## What ships

### 💰 Партнёрка — money affiliate program (new: services/partner_service.py)
The competitor's playbook, copied and improved: **40% of EVERY purchase a
referred user ever makes — forever**, not a one-time bonus.

- **Attribution** (`models.Referral`): one permanent row per converted
  referral, `UniqueConstraint(invitee_user_id)`. Registered inside
  `referral_service.apply_referral` (fail-silent, never breaks the credit
  grant). `referrer_of_user()` falls back to the legacy analytics marker
  (`ProductEvent referral_invited`) so pre-v3.37 referrals also earn.
- **Commission ledger** (`models.PartnerTransaction`): `accrue_commission()`
  is hooked into `payments.record_payment` — the single choke point both
  Stars (`successful_payment`) and FreeKassa (`_fk_notify`) flow through.
  Ruble value: FreeKassa parses `amount=` out of the webhook payload; Stars
  use the `STARS_FIAT_RUB` ladder with a 2 ₽/⭐ conservative fallback.
  Idempotent by `source_charge_id` (unique column + IntegrityError fallback),
  runs AFTER the payment commits and is fail-silent — a ledger hiccup can
  never roll back a purchase.
- **Withdrawal**: balance ≥ `PARTNER_MIN_PAYOUT_RUB` (500 ₽, env-tunable) →
  one tap on «💸 Вывести» creates a pending payout; every admin gets a DM with
  ✅ Выплачено / ❌ Отклонить buttons (admin-guarded, single guarded
  transition `pending → paid/cancelled`; cancel auto-refunds the balance).
  Payout methods copy is env-configurable (`PARTNER_PAYOUT_METHODS`).
- **Bot UI**: `/referral /invite /partner` render the partner screen (RU+EN):
  invited count, total earned, available balance, personal link, min payout,
  withdraw button + 5 FAQ answers (What/How/Withdraw/One-time?/Support).
  The 💰 Партнёрка button replaces 📨 Пригласить in the main reply keyboard
  (`MAIN_KB_ROWS`); `BotCommand('partner')` joins the command menu; the
  /start referral hint now teases the money commission.
- **Mini App**: 5th nav tab «💰 Партнёрка» — two stat boxes (people invited /
  earned ₽), pink copy-link button (clipboard + tg.showAlert fallback),
  disabled withdraw button under the minimum, FAQ accordion, localized RU+EN.
  `GET /webapp/api/partner` (HMAC-validated) + `POST …/partner/withdraw`
  (409 on duplicate pending request).

### 🌸 Anime girls in the public constructor
`style` is the new FIRST constructor step: «Реалистичная» (default, keeps
every legacy persona photorealistic) vs «Аниме».
- `build_avatar_prompt()` branches: anime opens with «Beautiful anime
  illustration of an adult woman, 2D cel-shaded…»; the face-swap variant
  demands the reference identity «faithfully translated into anime style».
- `build_persona_context()` / `custom_appearance_descriptors()` carry the
  style descriptor, and the app wizard + bot wizard pick the step up
  automatically (both walk `CONSTRUCTOR_STEPS`). EN labels: «Anime» /
  «Realistic», step title «Her style?». Anime cards get the 🌸 emoji.
- Scope note: the photo pipeline's hard-coded photorealistic scenes
  (photo_service lines 668/1186/1548) are a known future deep change; this
  release anime-fies avatar/persona/identity-lock level.

### 🌶 Пошлый режим — Premium-gated spicy toggle
- `users.spicy_mode` boolean (auto-migrated) + «🌶 Пошлый режим» switch in
  ⚙️ Настройки (RU+EN). Enabling requires an active Premium (alert + Premium
  pitch otherwise); disabling is always allowed.
- The flag survives a lapsed subscription, but the chat gate re-checks
  Premium on every message: `chat_service.reply()` injects the
  «ПОШЛЫЙ РЕЖИМ ВКЛЮЧЁН» lift (bolder flirt, dirtier innuendo, her
  initiative — graphic anatomical descriptions still off-limits) into the
  shared system-prompt composition, so the bot chat AND the Mini App chat
  both honor the switch. Lapsed Premium = mode silently sleeps.

## Config knobs (env-tunable)
`PARTNER_ENABLED` (1), `REFERRAL_COMMISSION_PCT` (40),
`PARTNER_MIN_PAYOUT_RUB` (500), `PARTNER_PAYOUT_METHODS`
(карта РФ, СБП, крипта (USDT)).

## Verification
- Runtime probe (`_probe_v3370.py`, throwaway): ledger math (Stars ladder,
  FreeKassa amounts, duplicate-charge idempotency, unknown-star fallback),
  below-min refusal, full payout cycle (pending → paid, double-settle
  rejected), cancel-refund, legacy fallback attribution, anime prompt shapes,
  wizard payloads, partner payload, keyboard rows, spicy flag round-trip —
  ALL PROBES PASSED.
- New static tests: `tests/test_v3370_partner_anime_spicy_static.py`;
  v319/v3350 constructor pins updated for the 12-step style-first wizard;
  26 test files had their version tuples extended to 3.37.0.
