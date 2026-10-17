"""V3.63.12: chat that hooks — voice samples, grown-up speech, one hook per reply, MiniMax sampling."""
import json
import random
from pathlib import Path

from services.character_service import build_system_prompt, get_character
from services.hook_service import MOVES, SKIP_INTENTS, hook_note
from services.voice_samples import MATURE_AGE, VOICE_SAMPLES, voice_samples_block

ROOT = Path(__file__).resolve().parents[1]


def test_every_stock_girl_has_voice_samples():
    ids = {json.loads(p.read_text(encoding='utf-8')).get('id')
           for p in (ROOT / 'data' / 'characters').glob('*.json') if not p.name.endswith('_dna.json')}
    ids.discard(None)
    assert ids <= set(VOICE_SAMPLES), ids - set(VOICE_SAMPLES)
    for cid, samples in VOICE_SAMPLES.items():
        assert len(samples) == 2, cid
        for user_line, her_line in samples:
            assert user_line and her_line and len(her_line) < 220, cid
            assert '[' not in her_line, cid


def test_samples_ride_in_her_prompt_and_say_not_to_copy():
    prompt = build_system_prompt(get_character('erika_01'), 'rel', [], character_id='erika_01')
    assert 'КАК ТЫ ЗВУЧИШЬ' in prompt and 'НИКОГДА не повторяй' in prompt
    assert 'Эрика: добрый. я как раз открыла вино' in prompt
    assert voice_samples_block('custom_xyz') == ''


def test_grown_women_lose_teen_slang_young_ones_keep_it():
    mature = build_system_prompt(get_character('erika_01'), 'rel', [], character_id='erika_01')
    young = build_system_prompt(get_character('sonya_01'), 'rel', [], character_id='sonya_01')
    assert get_character('erika_01')['age'] >= MATURE_AGE > get_character('sonya_01')['age']
    for slang in ('«нзч»', '«омг»', '«лол»', '«да ну нах»'):
        assert slang not in mature
        assert slang in young
    assert 'как взрослая женщина' in mature
    assert 'Второе сообщение отделяй пустой строкой' in young


def test_hook_note_rotates_and_skips_serious_turns():
    rng = random.Random(7)
    for intent in SKIP_INTENTS:
        assert hook_note(intent) == ('', '')
    last = ''
    for _ in range(30):
        note, move = hook_note('flirt', last, True, rng)
        assert move in MOVES and move != last
        assert note.startswith('Режиссёр') and MOVES[move] in note
        last = move
    for _ in range(30):
        assert hook_note('question', '', False, rng)[1] != 'callback'


def test_hook_wired_before_his_message_and_minimax_dialogue_sampling():
    chat = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
    hook_at = chat.index('hook = next_hook(user_id, character_id, behavior_kind')
    assert hook_at < chat.index('messages.append({"role": "user", "content": user_text})', hook_at)
    assert "temperature=1.0, purpose='dialogue'" in chat
    llm = (ROOT / 'services' / 'llm_provider_service.py').read_text(encoding='utf-8')
    assert "mm_kwargs['top_p'] = 0.95" in llm
    assert "MINIMAX_DIALOGUE_MODEL if purpose == 'dialogue' else MINIMAX_MODEL" in llm
