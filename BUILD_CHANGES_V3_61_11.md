# V3.61.11 — SpicyAPI enable_thinking refusal

- SpicyAPI started refusing `enable_thinking=false` on the edit model (error 40004). The request is now retried once with the flag flipped, and the accepted value is remembered per model, so «Раздеть» and other edits go through.
