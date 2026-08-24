# Build Changes — v3.16.11

## Fix: underwear rendered on top of clothes instead of underneath

In v3.16.10 the random underwear color/style was prepended as standalone
sentences ("Her underwear this set is... She is wearing a..."), so the image
model treated the lingerie as the primary outfit and rendered it over the
main clothes.

### `services/photo_service.py`
- **Rewrote** the underwear injection in `_build_prompt`: color and style are
  now framed strictly as the under-layer — "Beneath her main outfit, directly
  against her skin, she wears {color} lingerie ({style}). It is strictly the
  under-layer under her clothes and never replaces them — the main outfit
  stays fully on." — followed by the existing level underlay rule.

### `VERSION`
- Bumped to `3.16.11`.
