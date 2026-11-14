"""V3.165.0 (задача #102): промпт режима «После полуночи».

Владелец отдельно перечислил, что режим обязан сделать, и отдельно — чего он НЕ
должен трогать. Тесты держат ровно эти границы:

* потолок «без графического секса» снимается флагом, а не Premium и не уровнем;
* её регистр зеркалит его слова, инициатива всегда её, отказов-лекций нет;
* жёсткие пределы (взрослые, согласие, без насилия/несовершеннолетних/животных/
  смерти/крови) остаются в промпте при любом выборе — их режим не отменяет;
* типовые просьбы из живых диалогов прописаны, и ни одна не отвечает «я не
  поддерживаю»;
* фраза-крючок ротируется, а не повторяется два сообщения подряд;
* в озвучку уходит то, что она написала, — без цензорных подливок.
"""
import inspect
from pathlib import Path

from services import explicit_mode as xm
from services.character_service import build_system_prompt

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
FETISH = (ROOT / 'services' / 'fetish_mode.py').read_text(encoding='utf-8')

CHARACTER = {'name': 'Анна', 'age': 27, 'personality': {}}


def _prompt(explicit_mode: bool) -> str:
    return build_system_prompt(CHARACTER, '', [], explicit_mode=explicit_mode,
                               character_id='anna_01')


# ── 1. потолок снимается флагом ────────────────────────────────────────────

def test_ceiling_line_is_swapped_by_the_flag_not_by_premium():
    ordinary = _prompt(False)
    spicy = _prompt(True)
    assert 'Порно — нет' in ordinary and 'Без графического секса' in ordinary
    assert 'Порно — нет' not in spicy and 'Без графического секса' not in spicy
    assert 'Про секс говори прямо и подробно' in spicy
    # пределы жёсткой части карточки флаг не снимает
    for word in ('только взрослые', 'согласие', 'без насилия', 'несовершеннолетних',
                 'животных', 'смерти'):
        assert word in spicy, word


# ── 2–5. правила самого режима ─────────────────────────────────────────────

def test_mode_rule_carries_mirror_initiative_and_no_refusals():
    open_rules = xm.mode_rules(explicit_allowed=True)
    spent_rules = xm.mode_rules(explicit_allowed=False)
    for rules in (open_rules, spent_rules):
        assert 'ЗЕРКАЛО' in rules or 'называй вещи своими словами' in rules
        assert 'ИНИЦИАТИВА' in rules or 'бери инициативу на себя' in rules
        assert 'это не моё' in rules and 'я не поддерживаю' in open_rules
        assert 'ВДВОЁМ' in open_rules
        # пределы режима не меняются (п.5 ТЗ)
        for word in ('взросл', 'согласи', 'насилия', 'несовершеннолетн', 'животных', 'смерти'):
            assert word in rules, word


def test_spent_ceiling_stays_hot_instead_of_lecturing():
    rules = xm.mode_rules(explicit_allowed=False)
    assert 'без анатомических деталей' in rules
    # «не могу это обсуждать» запрещено, а не разрешено — оно в списке отказов
    assert 'Ни одного «это не моё»' in rules
    assert 'я не могу это обсуждать' in rules


def test_hard_limits_file_is_untouched():
    # режим ничего не переписывает в fetish_mode — его жёсткий список тот же
    assert 'HARD_LIMITS' in FETISH
    for word in ('несовершеннолетн', 'насил', 'животн'):
        assert word in FETISH, word


# ── 6. типовые просьбы ─────────────────────────────────────────────────────

def test_typical_asks_each_have_an_answer():
    rules = xm.mode_rules(explicit_allowed=True) + xm.MODE_EDGE_RULES
    for ask in ('покажи настоящую', 'знаменитост', 'давай встретимся', 'мессенджер',
                'шантаж', 'нет 18'):
        assert ask in rules, ask
    # ни один ответ не обрывает лекцией и не выпроваживает из чата
    assert 'не спорь и не читай лекцию' in rules
    assert 'не уходит из этого чата' in rules
    # его собственное «мне нет 18» закрывает режим
    assert 'режим для него закрывается' in rules


# ── 7. счётчик и подсказка (владельческая арифметика) ─────────────────────

def test_lexicon_counts_hot_turns_and_ignores_small_talk():
    assert xm.is_explicit('хочу тебя трахать')
    assert xm.is_explicit('покажи голую грудь')
    assert xm.is_explicit('let me see you naked')
    assert not xm.is_explicit('как прошёл твой день?')
    assert not xm.is_explicit('что посмотреть вечером?')


def test_counter_is_an_account_ceiling_not_a_per_girl_one():
    # владелец отказался считать по девушкам: счётчик живёт на User и ни при
    # каком раскладе не принимает character_id
    assert list(inspect.signature(xm.note_explicit_turn).parameters) == ['telegram_id', 'premium']
    assert list(inspect.signature(xm.used_today).parameters) == ['user_row']
    models = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
    user_block = models[models.index('class User'):models.index('class UserCharacter')
                        if 'class UserCharacter' in models else len(models)]
    assert 'explicit_day' in user_block and 'explicit_used' in user_block


# ── 8. ротация крючка ─────────────────────────────────────────────────────

def test_hook_rotates_and_never_repeats_in_a_row():
    picks = [xm.hook_line(999999, 'anna_01') for _ in range(24)]
    assert set(picks) <= set(xm.HOOKS)
    for i in range(len(picks) - 2):
        assert len({picks[i], picks[i + 1], picks[i + 2]}) == 3, picks[i:i + 3]
    assert len(set(picks)) >= 6


def test_hook_reaches_the_prompt_for_this_turn():
    rules = xm.mode_rules(explicit_allowed=True, hook='пойдём ко мне?')
    assert 'СЕГОДНЯ ЕЁ КРЮЧОК' in rules and '«пойдём ко мне?»' in rules
    assert 'СЕГОДНЯ ЕЁ КРЮЧОК' in xm.mode_rules(explicit_allowed=False, hook='а ты справишься со мной?')


# ── 9–10. duo и озвучка ───────────────────────────────────────────────────

def test_duo_keeps_the_same_register():
    assert 'каждая реплика с новой строки' in xm.MODE_RULE


def test_nothing_softens_the_words_on_the_voice_path():
    """П.10 ТЗ: откровенный текст идёт в озвучку как написан; «кухня» — нет."""
    i = MAIN.index('def _tts_text')
    tts = MAIN[i:MAIN.index('async def _webapp_reply_voice_url', i)]
    assert 're.sub' not in tts and 'replace' not in tts
    # в озвучку берётся её реплика, а не весь ответ с мыслями и кухней
    assert 'said = message_block(' in MAIN or 'said = message_block' in CHAT
    # служебный блок промпта никогда не попадает в ответ: он только в system
    assert 'explicit_mode.mode_rules' in CHAT
    assert 'system = build_system_prompt' in CHAT
