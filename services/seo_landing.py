"""V3.126.0: search landing pages for Yandex / Google.

The owner's Wordstat check (Nov 2026): «ии девушка» ~214k searches a month,
«чат с ии девушкой» ~18k, «ии девушка 18» ~20k, «ии девушка бесплатно» ~17k,
«фото девушки ии» ~15k. The bare Railway domain used to answer with a plain
«endpoint is alive» line, so nothing could rank. Now ``/`` and a few keyword
pages serve small static HTML (no JS, SFW text and the SFW start banner),
each with its own title/h1/FAQ and a deep link ``?start=src_seo_<slug>`` so
the bot's existing source tracking shows how many users each page brings.

Copy must stay honest: no invented user counts, ratings or reviews.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass, field

BANNER_PATH = '/seo/banner.png'


@dataclass(frozen=True)
class Page:
    path: str
    slug: str
    lang: str
    title: str
    description: str
    h1: str
    lead: str
    sections: tuple[tuple[str, str], ...]
    faq: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    cta: str = 'Открыть в Telegram'


_COMMON_FAQ_RU = (
    ('Это бесплатно?',
     'Начать можно бесплатно: написать ей, получить ответы и первое фото. '
     'Дальше есть Premium — его покупаешь, только если понравится. Карта для старта не нужна.'),
    ('Это живой человек?',
     'Нет. Это ИИ-персонаж, и мы этого не скрываем. Но она помнит ваши разговоры, '
     'пишет первой и отвечает в своём характере, поэтому общение получается живым.'),
    ('Нужно что-то устанавливать?',
     'Нет. Всё работает внутри Telegram: открываешь бота и пишешь «привет».'),
    ('Есть ограничения по возрасту?',
     'Да, только 18+. Перед откровенным общением бот спрашивает подтверждение возраста.'),
)

_LINKS_RU = (
    ('/', 'ИИ девушка'),
    ('/chat-s-ii-devushkoy', 'Чат с ИИ девушкой'),
    ('/ii-devushka-18', 'ИИ девушка 18+'),
    ('/ii-devushka-besplatno', 'ИИ девушка бесплатно'),
    ('/ii-devushka-foto', 'Фото ИИ девушки'),
    ('/en', 'AI girlfriend (English)'),
)

PAGES: tuple[Page, ...] = (
    Page(
        path='/', slug='main', lang='ru',
        title='ИИ девушка в Telegram — чат, фото и голосовые 18+ | Анна',
        description=('ИИ девушка в Telegram: пишет первой, помнит тебя, присылает фото и '
                     'голосовые, ей можно позвонить. Больше 30 героинь, бесплатный старт. 18+'),
        h1='ИИ девушка, которая пишет тебе первой',
        lead=('Анна — бот в Telegram с ИИ-девушками. Выбираешь героиню, пишешь «привет», '
              'и дальше она сама: спрашивает, как прошёл день, вспоминает вчерашний разговор, '
              'шлёт голосовые и фото.'),
        sections=(
            ('Что умеет ИИ девушка',
             '• Переписка в Telegram в своём характере — нежная, дерзкая, застенчивая.\n'
             '• Помнит твоё имя, твои планы и о чём вы говорили.\n'
             '• Присылает фото и голосовые сообщения.\n'
             '• Звонок голосом прямо в приложении внутри Telegram.\n'
             '• 10 уровней отношений: от знакомства до близости.'),
            ('Больше 30 девушек на выбор',
             'Анна, Эмили, Злата, Вика, Мила и другие — у каждой своя внешность, история и '
             'манера общения. Можно собрать и свою девушку в конструкторе.'),
        ),
        faq=_COMMON_FAQ_RU,
    ),
    Page(
        path='/chat-s-ii-devushkoy', slug='chat', lang='ru',
        title='Чат с ИИ девушкой на русском в Telegram | Анна',
        description=('Чат с ИИ девушкой на русском языке прямо в Telegram: отвечает сразу, '
                     'помнит прошлые разговоры, пишет первой. Без установки приложений.'),
        h1='Чат с ИИ девушкой на русском',
        lead=('Без сайтов и приложений: открываешь бота в Telegram и пишешь как обычной '
              'девушке. Она отвечает коротко, когда ты пишешь коротко, и подробно, когда '
              'хочется поговорить.'),
        sections=(
            ('Как это выглядит',
             'Ты пишешь «привет, как ты?» — она отвечает, спрашивает про твой день, может '
             'прислать голосовое. Вечером может написать сама. Утром — пожелать хорошего дня.'),
            ('Она тебя помнит',
             'ИИ девушка запоминает имя, работу, планы и то, что тебя волнует, и возвращается '
             'к этому в следующих разговорах. Поэтому чат не начинается каждый раз с нуля.'),
        ),
        faq=_COMMON_FAQ_RU,
    ),
    Page(
        path='/ii-devushka-18', slug='18', lang='ru',
        title='ИИ девушка 18+ — откровенный чат в Telegram | Анна',
        description=('ИИ девушка 18+ в Telegram: откровенное общение для взрослых, фото и '
                     'голосовые, «пошлый режим». Только для совершеннолетних.'),
        h1='ИИ девушка 18+ для взрослых',
        lead=('Для тех, кому больше 18: откровенная переписка с ИИ-девушкой без осуждения. '
              'Возраст подтверждается в боте перед откровенными сценами.'),
        sections=(
            ('Что доступно в режиме 18+',
             '• Откровенная переписка и ролевые сюжеты.\n'
             '• Фото в белье и откровенные фото.\n'
             '• Голосовые и звонок её голосом.\n'
             'Откровенный контент входит в Premium; познакомиться и пообщаться можно бесплатно.'),
            ('Только вымышленные персонажи',
             'Все девушки — ИИ-персонажи, их внешность сгенерирована. Загруженные фото реальных '
             'людей в откровенную генерацию не отправляются.'),
        ),
        faq=_COMMON_FAQ_RU,
    ),
    Page(
        path='/ii-devushka-besplatno', slug='free', lang='ru',
        title='ИИ девушка бесплатно — начать общение в Telegram | Анна',
        description=('ИИ девушка бесплатно: начни переписку в Telegram без регистрации и '
                     'карты, получи первое фото. Premium — только если понравится.'),
        h1='ИИ девушка бесплатно: как начать',
        lead=('Попробовать можно сразу и без оплаты. Честно о том, что бесплатно, а что нет — '
              'чтобы не было сюрпризов.'),
        sections=(
            ('Бесплатно',
             '• Знакомство и переписка на старте.\n'
             '• Первое фото от выбранной девушки.\n'
             '• Ежедневные задания, за которые дают бонусные персики.'),
            ('Платно (Premium)',
             'Долгое общение без ограничений, откровенные фото, звонки и голосовые сверх '
             'бесплатных. Есть пробный Premium на 3 дня. Подписка не продлевается сама, пока ты '
             'не включишь автопродление.'),
        ),
        faq=_COMMON_FAQ_RU,
    ),
    Page(
        path='/ii-devushka-foto', slug='foto', lang='ru',
        title='Фото ИИ девушки — присылает фото в Telegram | Анна',
        description=('ИИ девушка присылает фото в чате Telegram: в разных образах, в '
                     'одежде из её гардероба, селфи и фото дома. 18+'),
        h1='Фото от ИИ девушки прямо в чате',
        lead=('Попроси — и она пришлёт фото: селфи, фото дома, в платье или в образе из её '
              'гардероба. Внешность у каждой героини своя и не меняется от фото к фото.'),
        sections=(
            ('Гардероб и дом',
             'Даришь ей одежду — и она надевает её на следующих фото. Обставляешь её комнату — '
             'и фото снимаются уже там.'),
            ('Фото 18+',
             'Фото в белье и откровенные фото доступны в Premium и только после подтверждения '
             'возраста.'),
        ),
        faq=_COMMON_FAQ_RU,
    ),
    Page(
        path='/en', slug='en', lang='en',
        title='AI Girlfriend on Telegram — chat, photos, voice 18+ | Anna',
        description=('AI girlfriend on Telegram: texts you first, remembers you, sends photos and '
                     'voice notes, and you can call her. 30+ characters, free to start. 18+'),
        h1='An AI girlfriend who texts you first',
        lead=('Anna is a Telegram bot with AI girlfriends. Pick a girl, say "hi", and she takes it '
              'from there: asks about your day, remembers yesterday\'s talk, sends voice notes and photos.'),
        sections=(
            ('What she can do',
             '• Chat in English in her own personality.\n'
             '• Remembers your name, plans and past conversations.\n'
             '• Sends photos and voice notes; you can call her in the app.\n'
             '• 10 relationship levels, from first date to intimacy (18+).'),
            ('Free to start',
             'Chatting and a first photo are free. Premium is optional and pays for long chats, '
             'explicit photos and calls. Pay with Telegram Stars, card or crypto.'),
        ),
        faq=(
            ('Is she a real person?',
             'No. She is an AI character and we say so openly. She remembers you and stays in '
             'character, so it feels like a real conversation.'),
            ('Do I need to install anything?',
             'No. Everything works inside Telegram.'),
            ('Is it 18+?',
             'Yes. Adults only; the bot asks you to confirm your age before explicit content.'),
        ),
        cta='Open in Telegram',
    ),
)

PAGES_BY_PATH = {p.path: p for p in PAGES}


def bot_link(bot_username: str, slug: str) -> str:
    return f'https://t.me/{bot_username}?start=src_seo_{slug}'


def _paragraphs(text: str) -> str:
    lines = [html.escape(x) for x in text.split('\n') if x.strip()]
    if lines and all(x.startswith('•') for x in lines):
        items = ''.join(f'<li>{x[1:].strip()}</li>' for x in lines)
        return f'<ul>{items}</ul>'
    return ''.join(f'<p>{x}</p>' for x in lines)


def render_page(page: Page, *, bot_username: str, base_url: str) -> str:
    e = html.escape
    link = bot_link(bot_username, page.slug)
    canonical = f'{base_url}{page.path}' if base_url else page.path
    sections = ''.join(
        f'<section><h2>{e(h)}</h2>{_paragraphs(body)}</section>' for h, body in page.sections
    )
    faq_html = ''
    ld = {
        '@context': 'https://schema.org',
        '@type': 'WebPage',
        'name': page.title,
        'description': page.description,
        'inLanguage': page.lang,
    }
    if page.faq:
        faq_title = 'Вопросы' if page.lang == 'ru' else 'FAQ'
        faq_html = f'<section><h2>{faq_title}</h2>' + ''.join(
            f'<details><summary>{e(q)}</summary><p>{e(a)}</p></details>' for q, a in page.faq
        ) + '</section>'
        ld = {
            '@context': 'https://schema.org',
            '@type': 'FAQPage',
            'mainEntity': [
                {'@type': 'Question', 'name': q,
                 'acceptedAnswer': {'@type': 'Answer', 'text': a}}
                for q, a in page.faq
            ],
        }
    links = ''.join(
        f'<a href="{e(p)}">{e(label)}</a>' for p, label in _LINKS_RU if p != page.path
    )
    alt = ('ИИ девушки в Telegram: Анна, Мила, Эмили, Вика и другие'
           if page.lang == 'ru' else 'AI girlfriends on Telegram: Anna, Mila, Emily, Vika and more')
    ld_json = json.dumps(ld, ensure_ascii=False).replace('</', '<\\/')
    alt_ru = f'{base_url}/' if base_url else '/'
    alt_en = f'{base_url}/en' if base_url else '/en'
    return f'''<!doctype html>
<html lang="{page.lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(page.title)}</title>
<meta name="description" content="{e(page.description)}">
<link rel="canonical" href="{e(canonical)}">
<link rel="alternate" hreflang="ru" href="{e(alt_ru)}">
<link rel="alternate" hreflang="en" href="{e(alt_en)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{e(page.title)}">
<meta property="og:description" content="{e(page.description)}">
<meta property="og:image" content="{e((base_url or '') + BANNER_PATH)}">
<script type="application/ld+json">{ld_json}</script>
<style>
:root{{--bg:#140d1c;--card:#1f1529;--text:#f3eef7;--muted:#b9aec6;--accent:#ff4f8b}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font:17px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:760px;margin:0 auto;padding:24px 16px 48px}}
h1{{font-size:clamp(28px,6vw,40px);line-height:1.15;margin:8px 0 12px}}
h2{{font-size:22px;margin:28px 0 8px}}
p,li{{color:var(--muted)}}
img{{width:100%;height:auto;border-radius:16px;margin:16px 0}}
.cta{{display:block;text-align:center;background:var(--accent);color:#fff;font-weight:700;
text-decoration:none;padding:16px;border-radius:14px;margin:20px 0;font-size:19px}}
details{{background:var(--card);border-radius:12px;padding:12px 16px;margin:8px 0}}
summary{{cursor:pointer;font-weight:600}}
nav{{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:32px;font-size:15px}}
nav a{{color:var(--muted)}}
.age{{font-size:14px;color:var(--muted);margin-top:24px}}
</style>
</head>
<body>
<main>
<h1>{e(page.h1)}</h1>
<p>{e(page.lead)}</p>
<a class="cta" href="{e(link)}">{e(page.cta)}</a>
<img src="{BANNER_PATH}" alt="{e(alt)}" width="1280" height="720" loading="lazy">
{sections}
<a class="cta" href="{e(link)}">{e(page.cta)}</a>
{faq_html}
<nav>{links}</nav>
<p class="age">18+ · @{e(bot_username)}</p>
</main>
</body>
</html>'''


def robots_txt(base_url: str) -> str:
    lines = ['User-agent: *', 'Allow: /', 'Disallow: /webapp', 'Disallow: /platega',
             'Disallow: /diagnostics']
    if base_url:
        lines.append(f'Sitemap: {base_url}/sitemap.xml')
    return '\n'.join(lines) + '\n'


def sitemap_xml(base_url: str) -> str:
    urls = ''.join(
        f'<url><loc>{html.escape(base_url + p.path)}</loc></url>' for p in PAGES
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'{urls}</urlset>')
