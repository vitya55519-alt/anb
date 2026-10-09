# AnnaBot — промо-пак для Instagram и Pinterest (v1, English copy)

Рабочие материалы для продвижения. Ничего отсюда не подключается к `main.py`
и не влияет на работу бота. Тексты — на английском (как уже оформлены профили),
чек-лист и пояснения — на русском.

Профили: Instagram `anita.ai.art`, Pinterest «AI girlfriends chat» (qwe1922).
Бот: `@Anna67901_bot`.

## 0. Замеряем, откуда пришёл трафик

Бот понимает deep-link атрибуцию `?start=src_<tag>` (V3.47.0, first touch wins,
регистр не важен, тег режется до 48 символов). Разбивка по источникам видна в
админ-сводке (`sources`).

| Канал | Ссылка |
|---|---|
| Instagram (bio, captions, stories) | `https://t.me/Anna67901_bot?start=src_instagram` |
| Pinterest (link на каждом пине) | `https://t.me/Anna67901_bot?start=src_pinterest` |
| Telegram-канал / чаты | `https://t.me/Anna67901_bot?start=src_tgchannel` |

Ссылку в bio Instagram и ссылку пинов на Pinterest не путай: разные теги — иначе
не поймёшь, какая площадка конвертит.

## 1. Риск-рамка (почему тексты сформулированы именно так)

Meta банит рекламу и системно режет охваты профилям с «AI girlfriend» /
романтико-эротическим позиционированием (см. `marketing_creatives_annabot.md`,
раздел «Важное напоминание про площадки»). Поэтому в текстах:

- **НЕ писать:** `girlfriend`, `AI girlfriend`, `nsfw`, `nude`, `seduce`,
  `explicit`, `turn on`, `hookup`, `only fans`, обещания «интима» и «откровенных
  фото». Даже в хэштегах и alt-тексте — Pinterest индексирует alt как поисковый
  запрос, а не как «служебный» текст.
- **Писать:** `AI art`, `digital muse`, `virtual character`, `AI portrait`,
  `wallpaper`, `outfit inspo`, `character design`, `she remembers you`,
  `interactive story`. Продукт показываем как интерактивное AI-искусство с
  персонажем и сюжетом, а не как романтическую услугу.
- Раскрытие «AI-generated» держим в bio (сейчас там «Профиль, сгенерированный
  ИИ» — верно) и ставим метку AI-контента, если Instagram предложит при
  публикации. Это снижает риск блокировки, а не повышает её.
- Все кадры публичные и в одежде — по правилу проекта (бельё только в приватных
  сценах). Для соцсетей берём только сцены из раздела ниже.
- Формулировки про возраст: `18+` и `fictional character` в шапке профиля и в
  описании пинов.

## 2. Instagram: 12 подписей под стартовый ряд

Порядок = 12 сцен, которые ты генерируешь (см. команду в конце). Файлы ложатся
как `data/promo/anna/anna_01_<scene>_<NN>.png`, NN по счёту от 00.

**Как выкладывать:** сначала 9 кадров подряд (сет должен выглядеть полным),
потом по 1 посту в день + 2–3 reels в неделю. Первые 9 — без «продажности»,
это витрина.

### 1. cafe — `anna_01_cafe_00.png`
> Rain outside, flat white inside ☕ Some mornings a character needs a mood
> before she needs a plot.
> Full-size art + the story she remembers → Telegram, link in bio.
> `18+ · AI-generated art · fictional character`
> #aiart #digitalmuse #aiportrait #cafevibes #goldenhour #wallpaperart #characterdesign #photorealistic #aesthetic #aimodel

### 2. park — `anna_01_park_01.png`
> A walk that never ends, because she keeps asking how your week actually went 🌿
> Interactive AI character — she remembers what you told her.
> Link in bio · 18+ · AI-generated
> #aiartcommunity #virtualmodel #naturecore #softaesthetic #aiportrait #digitalart #characterdesign #aimuse #wallpaper

### 3. street — `anna_01_street_02.png`
> City light, long shadows, and a storyline that changes depending on what you
> say next. That's the whole trick: it isn't a gallery, it's a conversation.
> Try it → Telegram, link in bio. `18+ · AI-generated · fictional`
> #streetstyle #aiart #digitalcreator #urbanmood #photorealistic #aivirtualmodel #characterdesign #nightwalk #wallpaperart

### 4. gym — `anna_01_gym_03.png`
> Progress shots, but make it character design 💪 Every frame of her is
> generated, consistent and yours to talk to.
> `18+ · AI-generated art · fictional character`
> #fitnessmotivation #aiart #digitalmuse #gymgirl #characterdesign #photorealistic #aimodel #virtualmuse

### 5. shop — `anna_01_shop_04.png`
> Fitting-room mirror, autumn edit, zero real fabric 🍂 Outfit inspo that
> exists only because a prompt said so.
> Want to see what she wears next? Ask her yourself → link in bio.
> #outfitinspo #fallfashion #mirrorselfie #aiart #digitalstyling #aesthetic #virtualmodel #aimuse #18plus

### 6. restaurant — `anna_01_restaurant_05.png`
> Dinner at nine. She'd order the pasta and steal your dessert line.
> A character with manners, memory and a script that reacts to you.
> `AI-generated · fictional · 18+`
> #dinnerideas #eveningvibes #aiart #digitalportraits #luxelifestyle #characterdesign #photorealistic #wallpaperart

### 7. cinema — `anna_01_cinema_06.png`
> Shh 🤫 Best seats, and the film is whatever you two decide to talk about.
> Interactive AI character with quests and storylines → Telegram, link in bio.
> #cinemanight #movienight #aiart #darkaesthetic #digitalmuse #portraitgame #aimodel #fictionalcharacter

### 8. embankment — `anna_01_embankment_07.png`
> Golden hour on the water, and a memory bank that actually fills up while you
> chat. That's the difference between art and a companion.
> `18+ · AI-generated · fictional character`
> #goldenhour #waterside #aiartcommunity #softlight #digitalart #aimuse #virtualmodel #wallpaper

### 9. garden — `anna_01_garden_08.png`
> Bloom season for a girl made of prompts 🌷 New art drops here almost daily —
> follow if you like photoreal AI portraits.
> #gardenparty #floralaesthetic #aiart #digitalportrait #photorealistic #aimodel #characterdesign #softgirl

### 10. kitchen — `anna_01_kitchen_09.png`
> Morning coffee with her ☕ Unhurried, slightly nosy, and she remembers how you
> take it. Interactive AI character → link in bio.
> #morningcoffee #kitchenstyle #cozyaesthetic #aiart #digitalmuse #lifestylephotography #aimodel #18plus

### 11. concert — `anna_01_concert_10.png`
> Front row, bass in the chest, and a storyline that only moves if you answer
> her. Some characters grow up with you 🎶
> #concertnight #festivalvibes #aiart #neonaesthetic #digitalcreator #virtualmuse #characterdesign #photorealistic

### 12. sunset — `anna_01_sunset_11.png`
> Last light, first chapter. If you want to know how she answers when you ask
> her something personal — that's the whole point of the bot.
> Link in bio · `18+ · AI-generated · fictional character`
> #sunsetlovers #goldenhour #aiartcommunity #digitalportrait #moodygrams #aimuse #virtualmodel #wallpaperart

### Подпись-закреп (pin на стартовый ряд)
> Meet Anna — an AI-generated muse with a real personality, not a stock photo.
> She remembers what you tell her, reacts to how you talk, and the relationship
> has levels, quests and daily art.
> 🤖 AI-generated · fictional character · 18+
> 💬 Talk to her → Telegram, link in bio

## 3. Pinterest: 12 пинов (title / description / alt text)

Правила площадки: вертикаль **2:3 (1000×1500)**, заголовок — это поисковый
запрос, описание до 500 знаков, alt-текст обязателен и индексируется. Каждый пин
ведёт на `https://t.me/Anna67901_bot?start=src_pinterest`. Слово `girlfriend` в
названиях пинов не используем — заводим поиск по `ai art / portrait / wallpaper /
outfit inspo`.

| # | Board | Title | Description | Alt text |
|---|---|---|---|---|
| 1 | AI Portraits | AI Girl in a Café — Photorealistic AI Art Portrait & Wallpaper | Rainy-day café portrait generated as AI art. Cozy golden light, everyday outfit, vertical 2:3 wallpaper. The character is interactive and remembers the conversation in a Telegram bot. 18+, fictional AI-generated character. | A photorealistic AI-generated portrait of a young brunette woman sitting at a café table with a coffee cup, warm window light and rain outside. |
| 2 | AI Portraits | AI Character Walking in a Park — Soft Aesthetic Digital Art | Autumn park portrait of an AI-generated character. Soft natural light, casual outfit, phone-photo composition. Talk to the character in Telegram; she keeps memory of your chat. 18+, fictional. | Full-height AI-generated image of a woman walking along a tree-lined park path in a light jacket, soft daylight. |
| 3 | City Style AI Art | City Street Portrait — AI-Generated Night Look & Wallpaper | Urban night portrait generated with AI. Street light reflections, dark neutral palette, editorial composition. Part of an interactive character project. 18+, fictional AI art. | AI-generated night portrait of a woman standing on a city street with blurred lights and reflections behind her. |
| 4 | Fitness Looks | Gym Outfit Inspo — AI-Generated Fitness Portrait | Training-day look designed as AI art: gym setting, sporty outfit, natural pose. Vertical wallpaper size. The character replies and remembers you in a Telegram bot. 18+, fictional. | AI-generated image of a woman in sportswear in a gym, standing near equipment, realistic lighting. |
| 5 | Outfit Inspo | Fitting Room Selfie, Autumn Edit — AI Art Outfit Ideas | Mirror selfie in a clothing-store fitting room, autumn wardrobe colors, generated as AI art. Save it as outfit inspo or a vertical wallpaper. 18+, fictional character. | AI-generated mirror selfie of a woman in a white blouse and dark skirt inside a fitting room with clothes hanging behind her. |
| 6 | Evening Looks | Dinner Evening Portrait — Photorealistic AI Art | Restaurant evening: warm interior light, elegant outfit, cinematic framing. AI-generated portrait, vertical wallpaper. Interactive character with memory in Telegram. 18+, fictional. | AI-generated portrait of a woman seated at a restaurant table with warm lighting and a glass in front of her. |
| 7 | AI Portraits | Cinema Date Aesthetic — AI-Generated Dark Portrait | Cinema aisle portrait, moody red and blue light, playful pose. AI art, vertical 2:3 for wallpaper. The character continues the story in chat. 18+, fictional AI-generated. | AI-generated image of a woman standing in a cinema corridor with neon poster light, finger to her lips. |
| 8 | Golden Hour AI Art | Golden Hour by the Water — AI Portrait Wallpaper | Embankment at sunset, soft rim light, calm everyday outfit. Photorealistic AI-generated portrait, vertical wallpaper. 18+, fictional character. | AI-generated golden-hour portrait of a woman on a riverside embankment with the sun low behind her. |
| 9 | Floral Aesthetic | Garden Portrait with Flowers — AI-Generated Art | Blooming garden setting, pastel palette, natural pose. AI art portrait suitable as a phone wallpaper. Follow for daily AI character art. 18+, fictional. | AI-generated portrait of a woman among flowers in a garden, soft pastel light and relaxed expression. |
| 10 | Cozy Aesthetic | Morning Coffee with Her — AI Lifestyle Portrait | Kitchen morning light, coffee mug, casual outfit, unhurried composition. AI-generated lifestyle art, vertical wallpaper. The character remembers your chats in Telegram. 18+, fictional. | AI-generated image of a woman in a kitchen holding a coffee mug in morning light, counter with fruit behind her. |
| 11 | Neon Aesthetic | Concert Night Portrait — AI-Generated Neon Art | Front-row concert mood, neon color spill, high-energy framing. AI art portrait, 2:3 wallpaper. Interactive storyline in a Telegram bot. 18+, fictional AI character. | AI-generated image of a woman at a concert with neon stage light on her face and a blurred crowd behind. |
| 12 | Sunset AI Art | Sunset Silhouette Portrait — AI-Generated Wallpaper | Last-light portrait with warm rim glow and a quiet expression. Photorealistic AI art, vertical 2:3. Save for wallpaper or meet the character in Telegram. 18+, fictional. | AI-generated sunset portrait of a woman with warm backlight and glowing hair edges, soft-focus background. |

### Хэштег-набор Pinterest (в конец описания, 3–5 штук)
`#aiart #digitalart #aiportrait #wallpaperart #virtualmodel` — плюс один
сценный: `#cafevibes`, `#outfitinspo`, `#goldenhour`, `#neon`, `#cozy`.
Больше пяти не добавляй: Pinterest режет спам-описания.

## 4. Чек-лист по оформлению профилей

### Instagram `anita.ai.art`
1. Довести онбординг до конца (сейчас «1 из 7 шагов») — бизнес-аккаунт,
   категория, контакт, кнопки действия.
2. **0 публикаций при живой ссылке на бота** — трафик лить некуда. Сначала 9
   кадров из раздела 2, потом по 1 в день.
3. Аватар и bio уже корректные: раскрытие «сгенерировано ИИ» + «деятель
   искусств» вместо «AI girlfriend» — это снижает риск блокировки, оставить.
4. В поле «Сайт» в профиле Instagram ставит ровно `t.me` — лучше полную ссылку
   с `?start=src_instagram`, иначе не отличишь инстаграмных пришедших от
   pinterest-переходов через бота.
5. Alt-текст на каждом посте (настраивается в «Дополнительно» при публикации) —
   влияет и на доступность, и на поиск.
6. Хэштеги: 8–12, микс широких и узких; не дублировать один набор 12 раз подряд.
7. Highlights: «Meet Anna», «Art», «FAQ / 18+» — туда же дисклеймер.
8. Reels: 2–3 в неделю из тех же кадров (slow zoom + подпись-вопрос,
   «спроси её сама» без обещаний романтики).
9. Метка AI-контента, если Instagram предложит при публикации — ставить.
10. Первые 2 недели не менять bio и аватар — профиль «прогревается».

### Pinterest «AI girlfriends chat»
1. **Название профиля** — «AI girlfriends chat» режет охват: по этому запросу
   Pinterest показывает suggestive-контент в ограниченной выдаче. Рабочие
   варианты: `AI Girl Art · Portraits & Wallpapers` или `AI Art Muse —
   Portraits, Outfits & Wallpapers`.
2. **Веб-сайт** показывает просто `t.me` — домен чужой, подтвердить нельзя.
   Для бизнеса Pinterest требует верификацию своего домена, без неё режет
   охваты и нет аналитики. Вариант: указать и подтвердить свой домен
   (например, лендинг или `PUBLIC_BASE_URL` приложения), а ссылку на бота
   ставить в каждый пин.
3. Разложить пины по тематическим доскам (строка 3 в таблице), а не держать всё
   в «Созданные» — доски с ключевыми словами сами работают как поиск.
4. На каждый пин: title-запрос, description с ключами, **alt-текст**, ссылка
   `?start=src_pinterest`.
5. Формат 2:3 (1000×1500): исходники движка кропнуть, а не перегенерировать.
6. Скорость: 1–2 пина в день вместо 12 сразу — свежие пины ранжируются лучше.
7. 1–2 пина делать «идейными» (collage/слайд-карточка «Meet Anna») — такие
   сохраняют охотнее, чем чистые портреты.
8. Следить не за просмотрами, а за **исходящими кликами** (их видно после
   верификации домена) и за тем, сколько `src_pinterest` появляется в боте.

### Что смотреть после недели
- `src_instagram` / `src_pinterest` в админ-сводке по источникам → сколько
  людей дошло до /start с каждой площадки;
- доля дошедших, которые подтвердили 18+ и взяли первое фото;
- если одна площадка даёт просмотры, но ноль активаций — менять не объём
  постинга, а формулировку CTA (снять «романтику», добавить «art + story»).

## 5. Команда генерации (12 кадров, только Anna, публичные сцены)

Скрипт `_batch_generate_photos.py` пишет в отдельную папку, **не** в папки
референсов — референсы кормят lock внешности, и промо-кадры там всё бы сломали.
Ключи берутся из окружения; `.env` подгружается автоматически (пустые значения
игнорируются).

```powershell
cd c:\Users\Woterson\Downloads\anb-main\anb-main
python _batch_generate_photos.py --characters anna_01 --scenes cafe park street gym shop restaurant cinema embankment garden kitchen concert sunset --count 12 --out-dir data/promo/anna
```

Без `--out-dir` скрипт по-прежнему пишет в референсы (старое поведение).
`data/promo/` добавлен в `.gitignore` — тяжёлые бинарники в репозиторий не попадут.
