from __future__ import annotations
import asyncio
import datetime as dt
import re
from zoneinfo import ZoneInfo
from config import CHARACTER_ID
from services.llm_provider_service import generate_text
from services.character_service import get_character, build_system_prompt
from services.memory_service import get_recent_messages, get_memories, save_message, extract_memory
from services.relationship_service import record_user_message
from services.relationship_signals import infer_delta
from services.test_mode import get_stage as get_test_stage
from services.behavior_service import behavior_context, choose_behavior
from services.dialogue_guard_service import build_repetition_guard
from services.character_dna_service import competency_context, character_dna_context
from services.state_service import state_context, softly_evolve_state
from services.user_service import ensure_user, get_user
from services.access_service import is_premium
from services.adaptation_service import observe_message, maybe_analyze_profile, build_adaptation_context


def _time_context(telegram_id: int) -> str:
    user = get_user(telegram_id)
    if not user or not user.timezone:
        return ""
    try:
        now_local = dt.datetime.now(ZoneInfo(user.timezone))
        hour = now_local.hour
        if 5 <= hour < 12:
            tod = "утро"
        elif 12 <= hour < 18:
            tod = "день"
        elif 18 <= hour < 23:
            tod = "вечер"
        else:
            tod = "ночь"
        return (
            f"Сейчас у пользователя {now_local.strftime('%H:%M')} ({user.timezone}), "
            f"время суток: {tod}. Используй это для уместных приветствий и реплик."
        )
    except Exception:
        return ""


META = re.compile(r"\b(ты настоящ|ты реальн|ты человек|ты бот|ты ии|ты ai|искусственн|виртуальн)\b", re.I)
TECH = re.compile(r"\b(напиши код|код на|python|питон|скрипт|калькулятор|объясни|переведи|посчитай|реши)\b", re.I)
ASSISTANTY = re.compile(
    r"(чем (?:я )?могу помочь|что хочешь от [«\"]?виртуал|готов[а-я ]* к (?:проверке|испытанию)|"
    r"выбирай[,— -]+не томи|я здесь[, ]+чтобы|если хочешь[, ]+я могу|начинаю проверку|AI с большой буквы)", re.I
)


def _clean(answer: str) -> str:
    answer = (answer or "хм… я зависла на секунду 🙈").strip()
    answer = re.sub(r"^(Конечно|Разумеется|Понимаю тебя|Хорошо,? |Да,? (?:конечно|разумеется))[,!:。.\.\s]+", "", answer, flags=re.I)
    answer = re.sub(r"\n[-*•]\s", "\n", answer)  # strip markdown lists
    answer = re.sub(r"\*\*(.+?)\*\*", r"\1", answer)  # strip bold
    answer = re.sub(r"\n{3,}", "\n\n", answer)
    return answer.strip() or "хм… я зависла на секунду 🙈"


def _needs_rewrite(user_text: str, answer: str) -> bool:
    if ASSISTANTY.search(answer):
        return True
    if answer.count("?") > 2:  # tolerate more questions in natural conversation
        return True
    if not META.search(user_text) and re.search(r"\b(виртуалк|искусственн(?:ый|ая) интеллект|я (?:бот|AI|ИИ))\b", answer, re.I):
        return True
    if not TECH.search(user_text) and len(answer) > 800:  # allow longer natural responses
        return True
    if META.search(user_text) and len(answer) > 350:
        return True
    return False


async def _rewrite_if_needed(messages: list[dict], user_text: str, answer: str) -> str:
    if not _needs_rewrite(user_text, answer):
        return answer
    rewrite_messages = messages + [
        {"role": "assistant", "content": answer},
        {"role": "user", "content": (
            "[Редактор] Перепиши как живой человек в личке. Сохрани смысл, но убирай структуру AI-ответа. "
            "Пиши как в переписке: коротко, небрежно, с эмоциями. Можно сленг, можно с середины мысли. "
            "Убери «Конечно», «Разумеется», списки, нумерацию и лишние вопросы. "
            "Если спрошено про AI/реальность — коротко скажи что нет, но без лекций."
        )},
    ]
    r = await generate_text(rewrite_messages, max_tokens=280, temperature=0.8, purpose='rewrite')
    return _clean(r.text)


async def reply(user_id: int, user_name: str, user_text: str, language_code: str | None = None, character_id: str = CHARACTER_ID) -> str:
    db_user_id = ensure_user(user_id, user_name, language_code=language_code)
    observe_message(db_user_id, user_text, character_id)
    delta = infer_delta(user_text)
    test_stage = get_test_stage(user_id)
    if test_stage:
        from services.relationship_engine import build_relationship_context
        class _StageOnly:
            relationship_score = 0
            trust_score = 0
            intimacy_score = 0
        # Use the same stage guidance without modifying real scores.
        stage_prompts = {
            'stranger': 'Уровень 1 — знакомство. Легко, чувственно и с заметной химией; допустим лёгкий флирт и двусмысленность, но без фамильярности.',
            'acquaintance': 'Уровень 2 — уже знакомые. Больше узнавания, чувственного флирта, двусмысленностей и инициативы Анны.',
            'close': 'Уровень 3 — близкое общение. Теплее, больше callbacks и инициативы.',
            'intimate': 'Уровень 4 — доверие, активный чувственный флирт и эротическое напряжение без графических описаний; не в каждом сообщении.',
            'deeply_connected': 'Уровень 5 — очень близкие. Персонализация, память, уверенный взаимный флирт.',
            'committed': 'Уровень 6 — сложившаяся романтическая связь внутри ролевой модели. Нежность, привычность, общая история.'
        }
        rel_context = stage_prompts[test_stage] + ' Тестовый режим не упоминай и реальные баллы не меняй.'
    else:
        rel_context = await record_user_message(
            user_id, user_name,
            relationship=delta.relationship, trust=delta.trust, intimacy=delta.intimacy,
            event_type=delta.event_type, reason=delta.reason,
            character_id=character_id,
        )
    character = get_character(character_id)
    premium = is_premium(user_id)
    memories = get_memories(db_user_id, character_id, 40 if premium else 14)
    history = get_recent_messages(db_user_id, character_id, 30 if premium else 16)
    stage_to_level = {'stranger':1,'acquaintance':2,'close':3,'intimate':4,'deeply_connected':5,'committed':6}
    adaptation = build_adaptation_context(db_user_id, stage_to_level.get(test_stage or '', 0) or 1, character_id)
    if not test_stage:
        # Relationship context itself is authoritative; adaptation strength still grows conservatively with history.
        try:
            from services.photo_service import get_relationship_level
            adaptation = build_adaptation_context(db_user_id, get_relationship_level(user_id, character_id), character_id)
        except Exception:
            pass
    previous_user_text = next((m.content for m in reversed(history) if m.role == 'user'), '')
    behavior = behavior_context(user_text, previous_user_text)
    competency = competency_context(user_text, character_id)
    dna = character_dna_context(character_id)
    diversity = build_repetition_guard(history, user_text)
    system = build_system_prompt(
        character, rel_context, [m.content for m in memories], behavior + ('\n' + dna if dna else '') + ('\n' + competency if competency else '') + ('\n' + diversity if diversity else ''), state_context(user_id), adaptation,
        time_context=_time_context(user_id),
        character_id=character_id,
    )
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": user_text})
    behavior_kind = choose_behavior(user_text, previous_user_text).intent
    token_budget = 180 if behavior_kind == 'task_clarify' else (900 if behavior_kind == 'task_execute' else 320)
    r = await generate_text(messages, max_tokens=token_budget, temperature=0.9, purpose='dialogue')
    answer = _clean(r.text)
    answer = await _rewrite_if_needed(messages, user_text, answer)
    save_message(db_user_id, character_id, "user", user_text)
    save_message(db_user_id, character_id, "assistant", answer)
    await asyncio.gather(
        extract_memory(db_user_id, character_id, user_text),
        maybe_analyze_profile(db_user_id, character_id),
    )
    softly_evolve_state(user_id, user_text)
    return answer


async def proactive_reply(user_id: int, user_name: str, hours_inactive: int, language_code: str | None = None, character_id: str = CHARACTER_ID) -> str:
    db_user_id = ensure_user(user_id, user_name, language_code=language_code)
    character = get_character(character_id)
    memories = get_memories(db_user_id, character_id, 10)
    history = get_recent_messages(db_user_id, character_id, 8)
    from services.relationship_service import get_context
    rel_context = await get_context(user_id, character_id=character_id) or "Отношения только начинаются."
    try:
        from services.photo_service import get_relationship_level
        adaptation = build_adaptation_context(db_user_id, get_relationship_level(user_id, character_id), character_id)
    except Exception:
        adaptation = build_adaptation_context(db_user_id, 1, character_id)
    system = build_system_prompt(
        character, rel_context, [m.content for m in memories],
        "Напиши одну короткую спонтанную реплику первой. Не объясняй, зачем пишешь, и не обязательно задавай вопрос.",
        state_context(user_id), adaptation,
        time_context=_time_context(user_id),
        character_id=character_id,
    )
    messages = [{"role": "system", "content": system}] + [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": f"Пользователь не писал около {hours_inactive} часов. Напиши естественно первой, не упоминая отслеживание активности."})
    r = await generate_text(messages, max_tokens=100, temperature=0.95, purpose='proactive')
    answer = _clean(r.text)
    save_message(db_user_id, character_id, "assistant", answer)
    return answer
