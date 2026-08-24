# BUILD CHANGES v3.17.4

## Community photo pool: pool-first for free/story sets

Users asked that photos generated for one user also serve other users (e.g. a
park set generated for user 1 should be available to user 2) instead of every
request paying for a duplicate AI run.

- Every AI-generated frame already entered the shared pool since v3.16.9
  (`community_shared=True`); the pool was only used as a failure fallback.
- Now `deliver_photo` consults the pool **first** for `free`/`story` sets:
  when the pool holds a full unseen set (`PHOTO_SET_SIZE`) for this
  character+scene, it is delivered immediately with `provider='community_pool'`
  and `source_delivery_id` linking back to the original generation. Tracked
  via `photo_community_pool_served`.
- **Paid credit sets are unchanged**: they always generate fresh AI photos —
  paying users get unique content.
- AI generation still runs whenever the pool has no full unseen set, and every
  fresh frame keeps feeding the pool. The failure fallback order is unchanged
  (community pool → curated library).
- New flag `COMMUNITY_POOL_FIRST` (default `true`) — set to `false` to revert
  to the old always-generate policy without a redeploy.
- `_PRIVATE_LIBRARY_SCENES` extended with `peek` and `dressing` — lingerie-
  revealing scenes are never served from or top-upped by shared content.

## Tests
- Updated `test_v3169_community_pool_static.py` for the pool-first policy.
- New `tests/test_v3174_community_pool_first_static.py`: config flag,
  proactive block before generation, private-scene exclusion, pool feeding.
