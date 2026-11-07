from pathlib import Path

from services import seo_landing as s

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_every_page_renders_with_tracked_link():
    paths = set()
    for page in s.PAGES:
        body = s.render_page(page, bot_username='Anna67901_bot', base_url='https://x.example')
        assert f'?start=src_seo_{page.slug}' in body
        assert f'<title>{page.title.replace("&", "&amp;")}</title>' in body or '<title>' in body
        assert '18+' in body
        assert len(page.description) <= 200
        assert page.path not in paths
        paths.add(page.path)
    assert '/' in paths and '/en' in paths


def test_slugs_fit_source_tag_limit():
    for page in s.PAGES:
        assert len(f'seo_{page.slug}') <= 48 and page.slug == page.slug.lower()


def test_no_fake_social_proof():
    blob = ' '.join(s.render_page(p, bot_username='b', base_url='') for p in s.PAGES).lower()
    for bad in ('отзыв', 'пользователей уже', 'рейтинг', 'review', 'users already'):
        assert bad not in blob


def test_robots_and_sitemap():
    assert 'Sitemap: https://x.example/sitemap.xml' in s.robots_txt('https://x.example')
    assert 'Disallow: /webapp' in s.robots_txt('')
    xml = s.sitemap_xml('https://x.example')
    assert xml.count('<url>') == len(s.PAGES)


def test_routes_wired():
    assert "app.router.add_get('/robots.txt', _seo_robots)" in MAIN
    assert "app.router.add_get('/sitemap.xml', _seo_sitemap)" in MAIN
    assert 'seo_landing.PAGES' in MAIN
    assert "app.router.add_get('/healthz', _healthz)" in MAIN
