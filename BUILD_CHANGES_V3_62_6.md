# V3.62.6 — selfie hands, prompt quality, acquisition sources

- Handheld selfies keep ONE free hand: two-hand pose notes («arms crossed»,
  «both hands…») are swapped for one-hand poses and say the other hand holds
  the phone. A third arm appeared when the pose and the selfie camera fought.
- The SpicyAPI prompt fitter (V3.62.4) no longer drops the quality line or the
  phone-hand sentence of HANDS, and keeps frame chaining (REFERENCE IMAGE 3, now
  on its own line). Redundant identity sentences go first instead.
- «Раздеть»: the phone hand keeps the phone; never a third hand.
- /stats shows where new users came from (24h and 7d): src_ tags, friend
  invites, shared photos, any other ?start= link (now recorded), and «без метки».
