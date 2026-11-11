"""V3.137.0: kill the «старательная актриса» — no bookish explanations of her
own feelings, no analyzing his behavior out loud, show-not-tell, and a little
everyday carelessness. The bans live in the Russian prompt and in every other
language's directive."""
from pathlib import Path

from services.character_service import build_system_prompt, get_character
from services.hook_service import hook_note
from services.behavior_service import behavior_context
from services import lang_guard

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
LT = (ROOT / 'services' / 'live_talk.py').read_text(encoding='utf-8')


def _prompt(cid='alisa_01'):
    return build_system_prompt(get_character(cid), 'REL', [], character_id=cid)


def test_prompt_bans_meta_analysis_and_explanations():
    t = _prompt()
    assert 'Никогда не анализируй вслух его манеру писать' in t
    assert 'Не расписывай свои внутренние процессы' in t
    # show-not-tell (unconditional block)
    assert 'Не описывай свои чувства как в книге' in t
    assert 'Не объясняй, почему ты так ответила' in t
    assert 'Не проговаривай этот разбор вслух' in t


def test_prompt_allows_everyday_carelessness_but_keeps_initiative():
    t = _prompt()
    assert 'Иногда с маленькой буквы' in t
    assert 'блин' in t and 'ой' in t
    assert 'Можешь не соглашаться, подкалоть' in t
    # initiative stays: she must not wait for him to carry every topic
    assert 'не жди, что следующую тему всегда придумает он' in t


def test_hook_and_behavior_carry_the_ban():
    note, _move = hook_note('flirt', '', True)
    assert note, _move
    assert 'Без разбора его поведения и без объяснения своей реакции' in note
    ctx = behavior_context('привет, как ты?')
    assert 'Не анализируй вслух его манеру писать' in ctx


def test_live_talk_bans_the_meta_voice():
    assert '_NO_META' in LT
    assert 'Не анализируй вслух его поведение и не объясняй, почему ты так отвечаешь' in LT


def test_directive_bans_the_meta_voice_in_every_language():
    # the directive itself is a Russian meta-instruction; every language carries
    # the same style ban + initiative cue.
    for lang in ('ru', 'en', 'es', 'it', 'fr', 'zh', 'ja', 'bn'):
        d = lang_guard.directive(lang)
        assert 'как в мессенджере' in d and 'проявляй инициативу' in d, (lang, d)