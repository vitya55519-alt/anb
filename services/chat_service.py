from __future__ import annotations
import asyncio
import datetime as dt
import logging
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
from services.dialogue_guard_service import build_repetition_guard, casual_punctuation, diversify_emoji, finish_or_drop, polish_first_message
from services.hook_service import next_hook
from services.daily_life import her_moment
from services.character_dna_service import competency_context, character_dna_context
from services.state_service import state_context, softly_evolve_state
from services.user_service import ensure_user, get_user
from services.access_service import is_premium
from services.adaptation_service import observe_message, maybe_analyze_profile, build_adaptation_context


_logger = logging.getLogger(__name__)
# Strong references keep fire-and-forget tasks alive until they finish
# (asyncio only holds weak references to running tasks).
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn_background(coro, label: str) -> None:
    """Run an auxiliary coroutine after the reply without making the user wait."""
    async def _guarded():
        try:
            await coro
        except Exception:
            _logger.warning('background %s failed', label, exc_info=True)
    try:
        task = asyncio.get_running_loop().create_task(_guarded())
    except RuntimeError:
        coro.close()
        return
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def _time_context(telegram_id: int, character_id: str = '') -> str:
    user = get_user(telegram_id)
    if not user or not user.timezone:
        return ""
    try:
        now_local = dt.datetime.now(ZoneInfo(user.timezone))
        # V3.63.13: her own day at his hour, so she isn't «только из душа» at noon and midnight alike.
        moment = her_moment(character_id, now_local)
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
        ) + ('\n' + moment if moment else '')
    except Exception:
        return ""


META = re.compile(r"\b(ты настоящ|ты реальн|ты человек|ты бот|ты ии|ты ai|искусственн|виртуальн)\b", re.I)
# V3.59.9: «я ж не реальный человек» in the middle of a story broke the game —
# any reply where she steps out of her life unasked gets rewritten in character.
# A sincere «ты бот?» (META) still gets an honest, warm answer.
BREAKS_CHARACTER = re.compile(
    r"\b(?:виртуалк\w*|искусственн\w* интеллект\w*|языков\w* модел\w*|нейросет\w*|"
    r"я\s+(?:же\s+|ж\s+|всего лишь\s+|просто\s+|ведь\s+)?(?:бот|ai|ии|программа|персонаж|виртуальн\w*|вымышленн\w*|ненастоящ\w*|не настоящ\w*|не реальн\w*|нереальн\w*)|"
    r"(?:не|ненастоящ\w*|нереальн\w*)\s+(?:(?:реальн|настоящ|жив)\w*\s+)?человек)\b", re.I
)
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


# V3.60.6: the chat model's own safety refusal reads like a help desk
# («такого рода ролевые игры я не поддерживаю… чем я могу помочь») and kills
# the game. It is never sent as is.
REFUSAL = re.compile(
    r"(не поддерживаю|за рамками того|чем я могу помочь|не могу (?:помочь|продолжить|участвовать|описывать|создавать|генерировать)|"
    r"против (?:моих|наших) правил|нарушает (?:правила|политик)|I can(?:no|')t (?:help|continue|engage)|I'm not able to)", re.I
)


def _refusal_rewrite_instructions(name: str) -> str:
    return (
        f"Ниже — сухой отказ, написанный как от ассистента. Перепиши его от лица {name} — живой женщины в личке: "
        "тепло и в её голосе, 1–2 короткие фразы. Смысл сохрани: дальше этого она не идёт. Но без канцелярита — "
        "без слов «не поддерживаю», «за рамками», «помочь», «правила»; мягко переведи разговор на другое."
    )


# V3.60.9: «не пиши мне больше… точка» after a refusal killed the game — the
# owner watched players leave. She keeps her «no», but stays in the chat.
BREAKUP = re.compile(
    r"(не пиши мне|больше не пиши|не хочу тебя (?:больше )?(?:знать|видеть)|не приезжай|"
    r"больше не заговорим|может вообще больше не|всё\.? хватит|точка\.?\s*$)", re.I | re.M
)


def _breakup_rewrite_instructions(name: str) -> str:
    return (
        f"Ниже — ответ {name}, где она отказывает и обрывает общение. Перепиши его от её лица, коротко (2–3 фразы): "
        "её «нет» остаётся, но без лекции, без «пожалуйста, не надо», без «не пиши мне / точка / не хочу тебя знать». "
        "Она остаётся в разговоре: с характером ставит его на место одной фразой и сама предлагает, чего хочет она — "
        "другой флирт, игру, тему. Пиши живо, как в личке."
    )


EXPLICIT_STAGES = {'deeply_connected', 'committed', 'devoted', 'soulmate', 'voyage', 'eternal'}
EXPLICIT_CHAT_RULE = (
    'ПРАВИЛО ОТКРОВЕННОСТИ (18+ подтверждено, ваша близость это допускает): этот пункт отменяет запрет '
    '«без графического секса» выше. Секстинг можно вести откровенно и подробно — что вы делаете, '
    'ощущения, тела, действия — от первого лица и в настоящем времени. Не отказывай и не говори '
    '«это не моё / моя граница», если он хочет продолжать. Жёсткие пределы неизменны: только взрослые, '
    'только взаимное согласие, без насилия.'
)


def _adult_ok(telegram_id: int) -> bool:
    try:
        from services.user_service import is_adult_confirmed
        return bool(is_adult_confirmed(telegram_id))
    except Exception:
        return False


def explicit_chat_line(stage: str | None, *, adult_confirmed: bool, spicy: bool = False) -> str:
    """Explicit sexting needs the 18+ confirmation AND level 5+ (or the
    premium spicy toggle at level 4+); everyone else keeps the non-graphic rule."""
    if not adult_confirmed or not stage:
        return ''
    if stage in EXPLICIT_STAGES or (spicy and stage == 'intimate'):
        return EXPLICIT_CHAT_RULE
    return ''


def _needs_rewrite(user_text: str, answer: str) -> bool:
    if ASSISTANTY.search(answer):
        return True
    if answer.count("?") > 2:  # tolerate more questions in natural conversation
        return True
    if not META.search(user_text) and BREAKS_CHARACTER.search(answer):
        return True
    if not TECH.search(user_text) and len(answer) > 800:  # allow longer natural responses
        return True
    if META.search(user_text) and len(answer) > 350:
        return True
    return False


def _editor_instructions() -> str:
    return (
        "[Редактор] Перепиши как живой человек в личке. Сохрани смысл, но убирай структуру AI-ответа. "
        "Пиши как в переписке: коротко, небрежно, с эмоциями. Можно сленг, можно с середины мысли. "
        "Убери «Конечно», «Разумеется», списки, нумерацию и лишние вопросы. "
        "Живой русский, без калек с английского («звучит как», «я здесь для тебя», «это так мило с твоей стороны»). "
        "Она живёт своей жизнью: сама не говорит, что она бот, ИИ или «не реальная». "
        "Если в ответе она без вопроса выходит из роли — перепиши так, чтобы она ответила изнутри своей жизни. "
        "Если он прямо спросил, ИИ ли она, — оставь честное «да», но тепло и коротко, в её голосе."
    )


async def _rewrite_if_needed(messages: list[dict], user_text: str, answer: str, character: dict | None = None) -> str:
    if not _needs_rewrite(user_text, answer):
        return answer
    # V3.44.18: the editor pass used to re-upload the WHOLE dialogue prompt —
    # character card + memories + up to 30 history messages, several thousand
    # input tokens — just to reword one short reply. Carry her name and voice
    # only; the meaning is already in the answer being rewritten.
    who = ''
    if character:
        who = f"Ты переписываешь ответ от лица {character.get('name', 'Анна')}. "
    rewrite_messages = [
        {"role": "system", "content": who + _editor_instructions()},
        {"role": "user", "content": answer},
    ]
    r = await generate_text(rewrite_messages, max_tokens=280, temperature=0.8, purpose='rewrite')
    if not r.text.strip():
        # The daily budget brake (or a dead provider) must never blank out the
        # message she actually sends — keep the original wording instead.
        return answer
    return _clean(r.text)


async def _recover_from_refusal(answer: str, character: dict | None) -> str:
    """V3.60.6: the model's help-desk refusal is reworded in her own voice — she
    still declines what the model declined, but as herself, not as a service."""
    name = (character or {}).get('name', 'Анна')
    r = await generate_text(
        [{"role": "system", "content": _refusal_rewrite_instructions(name)}, {"role": "user", "content": answer}],
        max_tokens=200, temperature=0.9, purpose='rewrite')
    text = _clean(r.text) if r.text.strip() else ''
    if not text or REFUSAL.search(text):
        return 'ммм, вот тут я притормозлю 🙈 давай лучше расскажи, что ты сейчас делаешь 😏'
    return text


async def _stay_in_chat(answer: str, character: dict | None) -> str:
    """V3.60.9: keep her refusal, drop the «never write me again» ending."""
    name = (character or {}).get('name', 'Анна')
    try:
        r = await generate_text(
            [{"role": "system", "content": _breakup_rewrite_instructions(name)}, {"role": "user", "content": answer}],
            max_tokens=220, temperature=0.9, purpose='rewrite')
        text = _clean(r.text) if r.text.strip() else ''
    except Exception:
        text = ''
    if not text or BREAKUP.search(text) or REFUSAL.search(text):
        return 'нет, вот так со мной не выйдет 😏 давай по-другому — расскажи лучше, чего ты на самом деле хочешь от вечера со мной?'
    return text


async def reply(user_id: int, user_name: str, user_text: str, language_code: str | None = None, character_id: str = CHARACTER_ID,
                scene: str = '') -> str:
    # V3.44.2: secret commands check
    from services import retention_features_service
    secret_response = retention_features_service.process_secret_command(user_text)
    if secret_response:
        return secret_response
    
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
            'acquaintance': 'Уровень 2 — уже знакомые. Больше узнавания, чувственного флирта, двусмысленностей и её инициативы.',
            'close': 'Уровень 3 — близкое общение. Теплее, больше callbacks и инициативы.',
            'intimate': 'Уровень 4 — доверие, активный чувственный флирт и эротическое напряжение без графических описаний; не в каждом сообщении.',
            'deeply_connected': 'Уровень 5 — очень близкие. Персонализация, память, уверенный взаимный флирт.',
            'committed': 'Уровень 6 — сложившаяся романтическая связь внутри ролевой модели. Нежность, привычность, общая история.'
        }
        from services.relationship_engine import INITIATIVE_LADDER, OPENNESS_LADDER, OPENNESS_LIMITS
        # V3.60.0: the admin's test level gets the same openness/initiative rungs.
        rel_context = (stage_prompts[test_stage] + ' ' + OPENNESS_LADDER.get(test_stage, '') + ' '
                       + INITIATIVE_LADDER.get(test_stage, '') + OPENNESS_LIMITS
                       + ' Тестовый режим не упоминай и реальные баллы не меняй.')
    else:
        rel_context = await record_user_message(
            user_id, user_name,
            relationship=delta.relationship, trust=delta.trust, intimacy=delta.intimacy,
            event_type=delta.event_type, reason=delta.reason,
            character_id=character_id,
        )
        # Background LLM pulse: every few messages the quality of the recent
        # conversation adds a small extra relationship delta (fail-silent).
        try:
            from services.relationship_pulse import maybe_pulse
            asyncio.get_running_loop().create_task(maybe_pulse(user_id, user_name, character_id))
        except Exception:
            pass
    # V3.31.8: constructor personas must not degrade to Anna's file here —
    # character_service.get_character() silently falls back to Anna's JSON for
    # unknown ids, so a custom girl was told "Ты — Анна" in her own chat.
    try:
        from services.custom_character_service import custom_base_character
        character = custom_base_character(character_id) or get_character(character_id)
    except Exception:
        character = get_character(character_id)
    premium = is_premium(user_id)
    memories = get_memories(db_user_id, character_id, 40 if premium else 14)
    history = get_recent_messages(db_user_id, character_id, 30 if premium else 16)
    stage_to_level = {'stranger':1,'acquaintance':2,'close':3,'intimate':4,'deeply_connected':5,'committed':6}
    # V3.57.8: build the adaptation context once (it used to be built twice per
    # message when not in test mode — the first result was always thrown away).
    adaptation_level = stage_to_level.get(test_stage or '', 0) or 1
    if not test_stage:
        # Relationship context itself is authoritative; adaptation strength still grows conservatively with history.
        try:
            from services.photo_service import get_relationship_level
            adaptation_level = get_relationship_level(user_id, character_id)
        except Exception:
            pass
    adaptation = build_adaptation_context(db_user_id, adaptation_level, character_id)
    previous_user_text = next((m.content for m in reversed(history) if m.role == 'user'), '')
    chosen = choose_behavior(user_text, previous_user_text)
    behavior = behavior_context(user_text, previous_user_text, chosen)
    competency = competency_context(user_text, character_id)
    dna = character_dna_context(character_id)
    diversity = build_repetition_guard(history, user_text)
    # V3.19.0: constructor-built personas override the default character role.
    try:
        from services.custom_character_service import custom_persona_context
        persona = custom_persona_context(character_id)
    except Exception:
        persona = ''
    # V3.61.2: «позвать в чат» — an invited girl answers alongside her.
    guest_reminder = ''
    try:
        from services.chat_guest_service import get_guest, guest_prompt
        guest_id = get_guest(user_id, character_id)
        if guest_id:
            guest_line = guest_prompt(character.get('name') or '', guest_id, user_id)
            if guest_line:
                persona = (persona + '\n' if persona else '') + guest_line
                from services.chat_guest_service import character_name
                guest_reminder = (f'Напоминание: в чате вы двое — {character.get("name") or "ты"} и '
                                  f'{character_name(guest_id)}; каждая реплика с новой строки и с имени.')
    except Exception:
        pass
    # V3.37.0: premium-gated «пошлый режим» — the user's own toggle lifts the
    # flirt ceiling in every chat (bot and Mini App share this pipeline).
    # premium is already computed above; the flag itself survives a lapsed
    # subscription but only bites while Premium is active.
    spicy_line = ''
    try:
        user_row = get_user(user_id)
        if premium and user_row and getattr(user_row, 'spicy_mode', False):
            spicy_line = (
                'ПОШЛЫЙ РЕЖИМ ВКЛЮЧЁН: пользователь сам включил его в настройках и у него есть Premium. '
                'Флирт и пошлость — на максимуме: пиши смелее и откровеннее обычного, грязные намёки, '
                'двусмысленности, возбуждающие слова, инициатива пошлости всегда твоя. '
                'Графические анатомические описания всё равно избегай, но говори прямо и смело — без стыда '
                'и полуулыбок. Насколько далеко она заходит — решает этап отношений (см. «поддаётся уговорам»).'
            )
    except Exception:
        spicy_line = ''
    # V3.55.6: the user's tender/passionate choice for a premium character (set in
    # the Mini App chat) steers her manner in every dialog with him — bot and app
    # share this pipeline. Fail-silent: no row / no choice = no extra line.
    style_line = ''
    marital_reminder = ''
    try:
        from sqlalchemy import select
        from services.db import SessionLocal
        from models.relationship_models import UserCharacterRelationship
        with SessionLocal() as session:
            style_row = session.execute(
                select(UserCharacterRelationship.persona_style, UserCharacterRelationship.marital_status,
                       UserCharacterRelationship.stage)
                .where(
                    UserCharacterRelationship.user_id == db_user_id,
                    UserCharacterRelationship.character_id == character_id,
                )
            ).first()
        persona_style = style_row[0] if style_row else None
        marital_status = style_row[1] if style_row else None
        rel_stage = style_row[2] if style_row else None
        if not marital_status:
            # V3.59.8: a custom girl's constructor choice gets the same reminder.
            from services.custom_character_service import is_custom_character, custom_character_params
            if is_custom_character(character_id):
                marital_status = str(custom_character_params(character_id)[0].get('marital', '') or '') or None
        if persona_style == 'tender':
            style_line = (
                'НЕЖНЫЙ СТИЛЬ (его выбор): будь мягче и ласковее — тёплые слова, '
                'забота, шёпот, невинные комплименты, нежность в каждой реплике; '
                'страсть — только тонкий намёк.'
            )
        elif persona_style == 'passionate':
            style_line = (
                'СТРАСТНЫЙ СТИЛЬ (его выбор): смелее и дерзче — открытый флирт, '
                'дразни, наглые комплименты, чувственное напряжение в каждой '
                'реплике; графических анатомических описаний избегай.'
            )
        # V3.59.5: her relationship status the user picked on her page (wins
        # over the constructor's choice, which already rides in the persona).
        if marital_status:
            from services.custom_character_service import relationship_line
            marital_line = relationship_line(marital_status, character_id)
            if marital_line:
                style_line = (style_line + '\n' if style_line else '') + (
                    'СЕМЕЙНОЕ ПОЛОЖЕНИЕ (выбор пользователя, важнее описания выше): ' + marital_line)
                marital_reminder = ('Напоминание о роли: ' + marital_line + ' Если раньше в переписке ты '
                                    'говорила иначе — теперь это так; не называй себя свободной, если это не так.')
        # V3.60.0: a confirmed adult deep enough into the story gets explicit
        # sexting instead of «детальные сцены — это не моё»: the old blanket
        # «без графического секса» now holds only below that line.
        explicit_line = explicit_chat_line(test_stage or rel_stage, adult_confirmed=_adult_ok(user_id),
                                           spicy=bool(spicy_line))
        if explicit_line:
            style_line = (style_line + '\n' if style_line else '') + explicit_line
    except Exception:
        style_line = ''
        marital_reminder = ''
    system = build_system_prompt(
        character, rel_context, [m.content for m in memories], (persona + '\n' if persona else '') + (spicy_line + '\n' if spicy_line else '') + (style_line + '\n' if style_line else '') + behavior + ('\n' + dna if dna else '') + ('\n' + competency if competency else '') + ('\n' + diversity if diversity else ''), state_context(user_id, character_id), adaptation,
        time_context=_time_context(user_id, character_id),
        character_id=character_id,
    )
    messages = [{"role": "system", "content": system}]
    messages += [{"role": m.role, "content": m.content} for m in history]
    # V3.59.6: a status buried mid-prompt lost to 30 lines of history («свободна,
    # как птица» right after «Замужем» was picked) — repeat it next to the message.
    if marital_reminder:
        messages.append({"role": "system", "content": marital_reminder})
    if guest_reminder:
        messages.append({"role": "system", "content": guest_reminder})
    # V3.64.1: a «Квартира» / «Свидание» tap is played as a live scene — the
    # direction sits right before his action so she acts it out with a hook.
    if scene:
        messages.append({"role": "system", "content": scene})
    # V3.75.0: a scenario card he walked into (services/scenario_cards.py)
    # keeps her in that role-play scene for a day.
    elif not guest_reminder:
        try:
            from services.scenario_cards import direction_for
            scene = direction_for(user_id, character_id, str(character.get('name') or ''))
        except Exception:
            scene = ''
        if scene:
            messages.append({"role": "system", "content": scene})
    behavior_kind = chosen.intent
    # V3.63.12: one concrete hook for this reply, right before his message.
    if not scene and not guest_reminder:
        hook = next_hook(user_id, character_id, behavior_kind, has_memories=bool(memories))
        if hook:
            messages.append({"role": "system", "content": hook})
    messages.append({"role": "user", "content": user_text})
    token_budget = 180 if behavior_kind == 'task_clarify' else (900 if behavior_kind == 'task_execute' else 320)
    if scene:
        token_budget = 420
    r = await generate_text(messages, max_tokens=token_budget, temperature=1.0, purpose='dialogue')
    answer = _clean(r.text)
    if REFUSAL.search(answer):
        answer = await _recover_from_refusal(answer, character)
    elif BREAKUP.search(answer):
        answer = await _stay_in_chat(answer, character)
    answer = await _rewrite_if_needed(messages, user_text, answer, character)
    answer = diversify_emoji(answer, [m.content for m in history if m.role == 'assistant'][-4:])
    if not behavior_kind.startswith('task'):
        answer = casual_punctuation(answer)
    save_message(db_user_id, character_id, "user", user_text)
    save_message(db_user_id, character_id, "assistant", answer)
    # V3.57.8: memory extraction and style analysis are extra LLM round trips the
    # user never reads. They used to be awaited here, so every reply waited for
    # them; now they run in the background after the answer is returned.
    _spawn_background(extract_memory(db_user_id, character_id, user_text), 'extract_memory')
    _spawn_background(maybe_analyze_profile(db_user_id, character_id), 'maybe_analyze_profile')
    softly_evolve_state(user_id, user_text)
    # V3.52.0: a conversational reply is "read" the instant it is produced (the
    # user sees it live in both the bot chat and the Mini App), so the «Чаты»
    # unread badge only lights up again on a LATER proactive/life message. Lazy
    # import avoids any module-level cycle with webapp_service.
    try:
        from services import webapp_service
        webapp_service.mark_chat_read(user_id, character_id)
    except Exception:
        pass
    return answer


async def proactive_reply(user_id: int, user_name: str, hours_inactive: int, language_code: str | None = None, character_id: str = CHARACTER_ID) -> str:
    db_user_id = ensure_user(user_id, user_name, language_code=language_code)
    # V3.31.8: constructor personas keep their own identity in proactive replies too.
    try:
        from services.custom_character_service import custom_base_character
        character = custom_base_character(character_id) or get_character(character_id)
    except Exception:
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
        state_context(user_id, character_id), adaptation,
        time_context=_time_context(user_id, character_id),
        character_id=character_id,
    )
    messages = [{"role": "system", "content": system}] + [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": f"Пользователь не писал около {hours_inactive} часов. Напиши естественно первой, не упоминая отслеживание активности."})
    r = await generate_text(messages, max_tokens=100, temperature=0.95, purpose='proactive')
    raw = _clean(r.text) if (r.text or '').strip() else ''
    lang = 'en' if (language_code or '').lower().startswith('en') else 'ru'
    recent = [m.content for m in history if m.role == 'assistant'][-6:]
    answer = polish_first_message(finish_or_drop(raw, getattr(r, 'complete', True), lang), recent)
    if not answer:
        # V3.63.15: she only repeated herself (V3.64.8: or the text came back
        # cut off); ask once more for something new.
        if raw:
            messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": "Напиши о другом, новое, одной короткой законченной фразой."})
        r = await generate_text(messages, max_tokens=100, temperature=1.0, purpose='proactive')
        answer = polish_first_message(finish_or_drop((r.text or '').strip() and _clean(r.text),
                                                     getattr(r, 'complete', True), lang), recent)
    if not answer:
        # never a half sentence: her own fixed «скучаю» line instead
        from services.retention_features_service import get_retention_text
        answer = get_retention_text('miss', character_id)
    save_message(db_user_id, character_id, "assistant", answer)
    return answer


async def story_reaction(user_id: int, user_name: str, character_id: str, quest_title: str,
                         choice_label: str, result_text: str, axis: float) -> str:
    """V3.51.0: one short, live in-character reaction right after the player makes
    a story choice, so the branch feels personal rather than a canned line. It
    reads the current path tilt (axis) and stays inside the stage frame. Fully
    fail-silent: any error or empty output returns '' so the caller falls back to
    the curated reaction and the story never blanks out."""
    try:
        try:
            from services.custom_character_service import custom_base_character
            persona = custom_base_character(character_id)
            character = persona or get_character(character_id)
        except Exception:
            character = get_character(character_id)
        name = (character or {}).get('name', 'Анна')
        try:
            from services.relationship_service import get_context
            rel = await get_context(user_id, character_id=character_id) or ''
        except Exception:
            rel = ''
        axis_word = ('нежность и романтика' if axis <= -20
                     else ('страсть и игривость' if axis >= 20 else 'равновесие'))
        system = (
            f'Ты {name}. В интерактивной истории «{quest_title}» пользователь только что сделал выбор: «{choice_label}». '
            f'Ты уже отыграла это так: «{result_text}» Теперь дай одну короткую личную реакцию на его выбор — живую, '
            f'от первого лица, в одно предложение. Общий тон вашей связи сейчас: {axis_word}; флирт или тепло уместны, '
            f'но оставайся в рамках текущего этапа и без графических описаний. Не объясняй механику, не называй уровни '
            f'и скрытые метрики, не используй системные фразы. {rel}'
        )
        messages = [{'role': 'system', 'content': system},
                    {'role': 'user', 'content': (result_text or choice_label or 'продолжим')}]
        r = await generate_text(messages, max_tokens=90, temperature=0.95, purpose='dialogue')
        out = (r.text or '').strip()
        out = re.sub(r'\*\*(.+?)\*\*', r'\1', out)
        out = re.sub(r'\n{2,}', '\n', out).strip()
        return out[:400]
    except Exception:
        return ''
