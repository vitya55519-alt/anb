"""ТЗ V3.167.2 (владелец, 16.11): «попросил фото, а потом Раздеть — сделай
раздивание по логике: если нажал Раздеть, модель присылает ТОЖЕ фото, только без
одежды, чтобы была логическая цепочка». Правка платного кадра меняет ОДЕЖДУ и
ничего больше: поза, ракурс, кадрировка, свет и стены берутся из того снимка, под
которым он нажал кнопку. Цена, гейт 18+ и окно «раз один в сутки» не тронуты."""
import os
os.environ.setdefault('TELEGRAM_TOKEN', '123456:test-fake')
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
ACTION = MAIN[MAIN.index('async def _webapp_api_photo_action('):
              MAIN.index('async def _webapp_media_scene(')]


def _prompt(**kw):
    import main
    return main._undress_prompt(1, 'anna_01', **kw)[0]


def test_the_same_frame_lock_leads_the_paid_edit():
    import main
    prompt = _prompt()
    assert prompt.startswith(main.UNDRESS_NEW_SHOT_LOCK)
    lock = main.UNDRESS_NEW_SHOT_LOCK
    # V3.167.17: «Раздеть» = НОВЫЙ кадр, та же женщина, другая поза и место.
    for keep in ('a new photo of the same woman he is looking at in image 1',
                 'Her face, eyes, nose, smile, hair, makeup, nails, skin tone, figure and body shape are identical',
                 'Everything else is new: another pose, another camera height and distance, another place',
                 'Do not copy image 1',
                 'Jewellery is not clothing: what she wears as jewellery in image 1 stays on her'):
        assert keep in lock, keep


def test_no_pose_from_the_old_pool_survives_in_the_prompt():
    prompt = _prompt()
    # V3.167.17: старые позы из пула убраны, но «UNDRESS REVEAL:» — это маркер раздела, а не поза.
    for stale in ('on her hands and knees', 'she squats', 'she lies back on the bed',
                  'she kneels on the bed', 'she turns a little and looks back', 'lifts the hem',
                  'pulls the waistband down', 'slip off one shoulder', 'unzips or unbuttons the back',
                  'arms lifted over her head', 'she sits down and slides'):
        assert stale not in prompt, stale


def test_the_reveal_only_names_garments():
    import main
    assert main.UNDRESS_CLOTHES_OFF in _prompt()
    for garment in ('top', 'blouse', 'dress', 'jumpsuit', 'cardigan', 'jacket', 'coat', 'bra',
                    'panties', 'jeans', 'trousers', 'shorts', 'skirt', 'leggings', 'tights',
                    'socks', 'shoes'):
        assert garment in main.UNDRESS_CLOTHES_OFF, garment
    assert 'off her body and out of the frame' in main.UNDRESS_CLOTHES_OFF
    # мягкий заход — то же самое, только остаётся кружевное белье
    lace = main._undress_prompt(1, 'anna_01', safe=True)[0]
    assert main.UNDRESS_CLOTHES_LACE in lace and 'lace lingerie' in lace
    assert 'COMPLETELY NAKED' not in lace


def test_the_lock_is_the_last_thing_the_trimmer_touches():
    from services import private_photo_service as pps
    # V3.167.17: tier 3 держит NEW SHOT LOCK, SHOT PLACE, SHOT POSE, UNDRESS REVEAL, CLOTHES.
    assert 'NEW SHOT LOCK:' in pps._SPICY_TIERS[2] and 'CLOTHES:' in pps._SPICY_TIERS[2]
    assert 'SHOT PLACE:' in pps._SPICY_TIERS[2]
    assert 'SHOT POSE:' in pps._SPICY_TIERS[2]
    assert 'UNDRESS REVEAL:' in pps._SPICY_TIERS[2]
    assert pps._spicy_tier('NEW SHOT LOCK: a new photo of the same woman') == 3
    assert pps._spicy_tier('SHOT PLACE: the new photo is taken in') == 3
    assert pps._spicy_tier('SHOT POSE: in the new photo she is') == 3
    assert pps._spicy_tier('UNDRESS REVEAL: A new photo of the same woman') == 3
    assert pps._spicy_tier('CLOTHES: she wears nothing in the new photo') == 3
    fitted = pps._fit_spicy_prompt(_prompt())
    assert len(fitted) <= pps.SPICYAPI_PROMPT_MAX
    assert 'NEW SHOT LOCK:' in fitted and 'CLOTHES:' in fitted


def test_the_no_phone_pass_leaves_the_lock_first():
    from services.photo_service import no_phone_frame
    # V3.167.17: промпт начинается с NEW SHOT LOCK, и no_phone_frame его не сдвигает.
    assert no_phone_frame(_prompt()).startswith('NEW SHOT LOCK:')


def test_the_place_of_the_photo_he_is_looking_at_never_changes(monkeypatch):
    # V3.167.17 (владелец, «Раздеть» = НОВЫЙ кадр): место берётся из пула UNDRESS_SHOTS
    # (только приватные), и SHOT PLACE прямо запрещает публичные venues.
    import main
    place_line = main.UNDRESS_SHOT_PLACE
    assert place_line.startswith('SHOT PLACE:')
    assert 'private place' in place_line
    for public in ('street', 'bar', 'club', 'restaurant', 'office', 'gym', 'mall'):
        assert public in place_line, public
    prompt = _prompt()
    assert 'SHOT PLACE:' in prompt
    # прежних правил больше нет в модуле — их не вернёшь случайно
    assert not hasattr(main, 'UNDRESS_PLACE_LOCK')
    assert not hasattr(main, 'UNDRESS_PLACE_TAIL') and not hasattr(main, 'UNDRESS_CARD_PLACE')


def test_her_line_names_the_frame_he_is_looking_at():
    import main
    # V3.167.17: реплики говорят про новый кадр, новую позу, новый ракурс.
    tied = [line for line in main.UNDRESS_LINES
            if 'переставилась' in line or 'другая поза' in line or 'новый ракурс' in line]
    assert len(tied) >= 3, tied


def test_the_button_still_edits_the_photo_he_tapped():
    assert 'media_url = str(body.get(\'media_url\', \'\'))' in ACTION
    assert "src_url = media_url.split('?', 1)[0]" in ACTION
    assert 'refs = [src, f\'{PUBLIC_BASE_URL}/webapp/photo/{character_id}?i=0\']' in ACTION
    assert '_spicyapi_render(SPICYAPI_IMAGE_MODEL, prompt, refs, scene=\'undress\', breaker=False)' in ACTION


def test_the_undress_economy_is_untouched():
    import config
    assert config.UNDRESS_PEACH_COST == config.EXPLICIT_PHOTO_PEACH_COST == 250
    assert 'if not is_adult_confirmed(telegram_id):' in ACTION
    assert 'undress_nudity.is_nude(telegram_id, character_id)' in ACTION
    assert 'spend_photo_peaches(telegram_id, UNDRESS_PEACH_COST)' in ACTION
