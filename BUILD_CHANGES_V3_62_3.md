# V3.62.3 — photo failure shows the real SpicyAPI cause

When SpicyAPI refused a photo and the fal fallback failed too, the admin toast
showed only fal's error (e.g. `transport_ReadError`). Now the reason carries
both legs: `spicyapi/<cause> → seedream45/<cause>`, and SpicyAPI's
`breaker_open` / `empty_result` include its last recorded error.
