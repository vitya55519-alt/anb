# AnnaBot V3.10.4 — Anna Visual Identity Engine v2

## Why
GPT Image 2 ordinary lifestyle generations could preserve Anna's general face while averaging her established body proportions toward a generic slim silhouette. This was most visible in mirror, gym, cafe/restaurant, seated and full-body scenes.

## Changes
- Split Anna visual identity into `ANNA_FACE_IDENTITY` and `ANNA_BODY_IDENTITY`.
- Added ordered dual-reference GPT Image workflow: face anchor first, canonical body anchor second.
- Added approved canonical body anchor `data/references/anna/00_body_canonical_v1.jpg`.
- Added `OPENAI_REFERENCE_PROTOCOL` so clothing/background from the body anchor are not copied.
- Added `BODY_REINFORCEMENT` for drift-prone ordinary scenes.
- Removed the old OpenAI wording that could be interpreted as suppressing/flattening body traits.
- General-audience safety now explicitly changes coverage/styling, never Anna's body geometry.
- Safe retry preserves both face and body identity.
- Updated Anna visual identity metadata/version.

## Provider routing
- GPT Image 2 remains the ordinary fully clothed lifestyle/fashion provider.
- Seedream 4.5 routing is unchanged for configured personal/private-fashion categories.
- Existing library-first delivery is unchanged.

## Deployment packaging
This release ZIP is intentionally flat: `main.py`, `requirements.txt`, `railway.toml`, etc. are at ZIP root so GitHub/Railway does not receive an extra wrapper directory.
