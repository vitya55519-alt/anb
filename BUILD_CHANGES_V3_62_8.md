# V3.62.8 — Premium purchase fixes

- The Stars 3-month plan (`premium_quarter`, 1200★) passed pre_checkout by
  default and was never granted in successful_payment: money taken, nothing
  switched on. Now validated against PREMIUM_QUARTERLY_STARS, granted (90 days +
  credits) and tracked as `stars_purchase`. Its button also answers the tap.
- Card/SBP (Platega) invoice is a «💳 Оплатить» button instead of a bare URL.
- New events: `platega_link_created`, `platega_paid`.
