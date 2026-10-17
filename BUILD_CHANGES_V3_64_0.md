# V3.64.0

- Erika: modern, attractive wardrobe (satin slips, leather, body-con dresses, cropped blazers, heels) and modern hairstyles; the old warm-neutral cashmere/turtleneck look and the generic knit pool no longer reach her photos (`wardrobe_exclusive`).
- Community personas: a persona row with empty constructor params no longer falls back to `data/characters/<id>.json` (FileNotFoundError on every selfie) nor to Anna's chat profile; she is built from her own row.
- App chat: a failed photo shows «Не получилось нарисовать», not «Не получилось ответить»; 400s of `/webapp/api/chat/media` are logged with the reason.
