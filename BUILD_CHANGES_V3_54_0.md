# V3.54.0 — «Своё фото → картинка / видео» (Studio Upload Media)

## Что добавлено
Вкладку «Картинки» теперь можно использовать со **своим фото**:
- **🖼 Картинка** — можно приложить своё фото, и студия сделает image-to-image:
  результат сохраняет узнаваемость человека, но стилизуется промптом и выбранным
  стилем/форматом. Без фото — прежнее поведение (текст → картинка, 10 🍑).
- **🎬 Видео** (новое, 10 🍑) — оживляет загруженное фото (image-to-video) с
  необязательным промптом движения; без фото сначала рендерится картинка по
  промпту, и анимируется уже этот кадр.

Наверху студии — переключатель режимов 🖼/🎬; строка «Стиль/Формат» показывается
только в режиме картинки. Результат видео отдаётся инлайн-плеером
`<video controls playsinline>`; отдельная галерея видео — вне скоупа (видна в
админ-фиде генераций).

## Безопасность и границы (зафиксировано)
- **Загруженное фото никогда не сохраняется** — только in-memory/temp-файл на
  время одного рендера, удаляется в `finally` при любом исходе.
- **img2img идёт ТОЛЬКО по цензурированным движкам** (`generate_custom_avatar`:
  Seedream face-swap → Gemini fallback): настоящее загруженное лицо не попадает
  в uncensored-движок даже у подтверждённых 18+ — никаких NSFW-дипфейков.
- **Нейтральный motion-промпт** для видео из своего фото — чувственный пресет
  бота (`SENSUAL_ANIMATION_PROMPT`) к загруженным лицам не применяется.
- Guardrails загрузки: декод ≤ **8 МБ**, mime ∈ {jpeg, png, webp}; те же
  проверки повторяются на клиенте. Требуется подтверждение 18+ (`has_accepted`).
- Списание 🍑 (картинка 10, видео 10) — **только после успешного рендера**;
  упавшая генерация ничего не стоит.

## Изменения по файлам
- **services/webapp_service.py**: `WEBAPP_VIDEO_COST_CREDITS = 10`;
  `STUDIO_UPLOAD_MAX_BYTES` (8 МБ) + `STUDIO_UPLOAD_MIME_EXT`;
  `decode_data_image(data_url)` — парсит `data:<mime>;base64,…`, валидирует
  mime/размер, возвращает `(bytes, mime, ext)` или `None` (fail-safe).
- **main.py**:
  - `_webapp_api_picture_generate` принимает опциональное поле `image`
    (data URL) → temp-файл → `reference_path` в
    `generate_custom_avatar(final_prompt, ref_path)`; при наличии фото
    uncensored-ветка 18+ отключается (`adult_ok = … and ref_path is None`);
    temp-файл удаляется в `finally`.
  - новый `POST /webapp/api/studio/video` (`_webapp_api_studio_video`):
    auth → блокировка промпта → consent → проверка 🍑; исходный кадр — загруженное
    фото или картинка из промпта (тот же цензурированный путь); цепочка движков
    как у бота: Gemini/Veo → Replicate → fal → HF, первый успех побеждает,
    каждый вызов пишется в `record_provider('studio_video/…')`; успех →
    `save_chat_media(..., 'mp4', 'video/mp4')` (Postgres, переживает редеплой) →
    `record_generation(kind='video')` → `spend_peaches` → `{ok, file, credits_left}`;
    провал всех движков — без списания, `{ok:false, error:'gen'}` (reason — только
    админу).
- **webapp/index.html**: `PIC_MODE`/`PIC_UPLOAD`, сегментный переключатель
  🖼/🎬 (`switchStudioMode()` — пробрасывает введённый промпт и перезаполняет
  галерею), «📎 Своё фото» (`<input type="file" accept="image/*">` +
  `FileReader` → data URL) с превью и «Убрать», `generatePicture()` шлёт `image`
  при наличии фото, новый `generateStudioVideo()` c обработкой 401/402/403/400 и
  видео-плеером. Ключи i18n `mode_pic/mode_video/upload_photo/upload_hint/
  upload_remove/video_prompt_ph/video_cost/video_generate/video_wait/video_fail/
  need_prompt_or_photo` во всех 7 локалях (en/ru/es/it/fr/zh/ja).

## Тесты
- `tests/test_v3540_studio_media_static.py` — 7 static-пинов: цена и guardrails
  декодера; img2img только по цензурированному пути + unlink temp; наличие и
  wiring роута видео; цепочка движков + нейтральный motion (отрицание SENSUAL
  внутри обработчика); порядок save→charge и «провал до списания»; SPA-пины
  (PIC_MODE/PIC_UPLOAD, file input, `<video`, endpoint); наличие всех ключей
  в ≥7 локалях.
- Паритет базовой линии: `pytest -q --continue-on-collection-errors` →
  17 failed / 953 passed / 1 error + 7 новых зелёных.

## Что не сделано (осознанно)
- Нет новой таблицы/колонки; загруженные фото не хранятся.
- Отдельная галерея «мои видео» и пресеты движения — потенциальный follow-up.
- `VERSION` не трогали.
