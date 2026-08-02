# Anna visual identity references

This folder contains the six adult AI-character reference images supplied for Anna in the project conversation.

Identity anchors:
- face and facial proportions
- long dark-brown hair
- eyes / brows / lips
- adult body proportions
- overall photographic style

Scene variables:
- clothing
- location
- pose
- lighting
- mood

For production image generation, use these as reference inputs with an image model that supports image conditioning/editing. The current `photo_service.py` is deliberately provider-neutral at the architecture level; its simple text-only fallback does not guarantee identity consistency.
