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
    assert prompt.startswith(main.UNDRESS_SAME_FRAME_LOCK)
    lock = main.UNDRESS_SAME_FRAME_LOCK
    for keep in ('the SAME photo he is looking at now, only without her clothes',
                 'her pose, head tilt, arm, hand and leg positions',
                 'the same camera angle, height, distance, crop and framing',
                 'the same room, background, furniture and objects',
                 'the same time of day, light and colours',
                 'Take her clothes off and change nothing else',
                 'This lock beats every pose, place or scene line below it'):
        assert keep in lock, keep
    assert 'do not re-pose her, do not turn her around, do not move her' in lock


def test_no_pose_from_the_old_pool_survives_in_the_prompt():
    prompt = _prompt()
    for stale in ('REVEAL:', 'on her hands and knees', 'she squats', 'she lies back on the bed',
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
    assert 'SAME FRAME LOCK:' in pps._SPICY_TIERS[2] and 'CLOTHES:' in pps._SPICY_TIERS[2]
    assert pps._spicy_tier('SAME FRAME LOCK: this is the SAME photo') == 3
    assert pps._spicy_tier('CLOTHES: every garment she wears in image 1') == 3
    fitted = pps._fit_spicy_prompt(_prompt())
    assert len(fitted) <= pps.SPICYAPI_PROMPT_MAX
    assert 'SAME FRAME LOCK:' in fitted and 'CLOTHES:' in fitted


def test_the_no_phone_pass_leaves_the_lock_first():
    from services.photo_service import no_phone_frame
    assert no_phone_frame(_prompt()).startswith('SAME FRAME LOCK:')


def test_the_public_place_stays_the_one_exception():
    import main
    tail = main.UNDRESS_PLACE_TAIL
    assert 'PLACE: keep the room of image 1 when it is already private' in tail
    assert 'her bedroom or a hotel room replaces those walls, and that is the ONLY change to the photo' in tail
    assert 'Her pose, hands, body, face, hair, light, camera angle and framing stay exactly as in image 1' in tail
    assert 'the same-frame lock' in tail
    # когда её слова назвали комнату, правка не трогает даже её
    card = main.UNDRESS_CARD_PLACE.format(place='a kitchen, evening light')
    assert 'keep it, its walls, its furniture and its light exactly as image 1 shows them' in card
    assert 'her pose, camera angle, framing and light do not change' in card


def test_her_line_names_the_frame_he_is_looking_at():
    import main
    tied = [line for line in main.UNDRESS_LINES
            if 'тот же' in line or 'с этого фото' in line]
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
