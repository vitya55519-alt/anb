# V3.62.4 — SpicyAPI prompt cap (photos were all failing)

SpicyAPI began rejecting prompts over 5000 characters (HTTP 400). Scene prompts
run 7–10k, so every selfie failed and fell to fal, which also failed.
`_fit_spicy_prompt` now shrinks each SpicyAPI prompt to 4900 characters: drops
the least important lines (lighting, season, mood…), then cuts trailing
sentences from the longest lines, keeping identity, the adult lock, scene,
wardrobe and frame instructions to the end.
