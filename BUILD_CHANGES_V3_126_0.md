# V3.126.0 — посадочные страницы для Яндекса и Google

- `/` на домене Railway больше не «endpoint is alive», а страница «ИИ девушка в Telegram».
- Ещё 5 страниц под запросы из Wordstat: `/chat-s-ii-devushkoy`, `/ii-devushka-18`,
  `/ii-devushka-besplatno`, `/ii-devushka-foto`, `/en` (AI girlfriend).
- Каждая кнопка ведёт в бота с `?start=src_seo_<slug>`: в статистике источников видно, сколько людей привела каждая страница.
- `/robots.txt`, `/sitemap.xml`, баннер `/seo/banner.png` (стартовый баннер, без откровенного).
- Тексты честные: без выдуманных цифр, отзывов и рейтингов. Проверка здоровья по-прежнему на `/healthz`.
