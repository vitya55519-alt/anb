# V3.62.9 — she offers Premium −30% at the first level-up

Nobody saw Premium on day one (first 24h unlimited, first limit gives a free
demo; 0 purchases in 30 days). Owner chose the «soft offer». On the first
level-up to level 2+ a non-premium user gets one message in her voice with a
«⭐ Premium −30% — 350⭐» button: it opens the existing one-time 24h discount
window (offer_discount), so it fires once per user. The paywall opened from it
now logs `paywall_view` (source=retention); the offer logs
`premium_offer_levelup`. Limits are unchanged.
