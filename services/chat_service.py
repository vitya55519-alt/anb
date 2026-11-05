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


# V3.97.0: «хм… я зависла на секунду 🙈» went out 141 times a week whenever
# both providers came back empty — the same robotic line, even to «целую, я
# поехал». When nothing came back she now answers like a busy live girl, with
# a different line each time, in his language.
STALL_LINES_RU = (
    'ой, секунду, мне тут звонят 🙈 не уходи, ладно?',
    'подожди, отвлеклась на минутку… так, о чём ты? 😌',
    'ммм, я тут задумалась над тем, что ты написал 😏 скажи ещё раз, по-другому',
    'прости, подруга написала, отвлекла 🙈 я снова только твоя',
    'так, я перечитала твоё сообщение и улыбаюсь как дурочка 😊 продолжай',
    'стоп, повтори, я хочу это прочитать ещё раз 😏',
)
STALL_LINES_EN = (
    'oops, one sec, someone is calling me 🙈 don\'t go anywhere, ok?',
    'sorry, got distracted for a moment… so, where were we? 😌',
    'hmm, I\'m still thinking about what you wrote 😏 say it again, differently',
    'my friend just texted me 🙈 I\'m all yours again',
)


def stall_line(lang: str = 'ru', recent: list[str] | None = None) -> str:
    import random
    pool = STALL_LINES_EN if lang == 'en' else STALL_LINES_RU
    recent_set = {(r or '').strip() for r in (recent or [])}
    fresh = [p for p in pool if p not in recent_set] or list(pool)
    return random.choice(fresh)


def _clean(answer: str) -> str:
    answer = (answer or stall_line()).strip()
    answer = re.sub(r"^(Конечно|Разумеется|Понимаю тебя|Хорошо,? |Да,? (?:конечно|разумеется))[,!:。.\.\s]+", "", answer, flags=re.I)
    answer = re.sub(r"\n[-*•]\s", "\n", answer)  # strip markdown lists
    answer = re.sub(r"\*\*(.+?)\*\*", r"\1", answer)  # strip bold
    answer = re.sub(r"\n{3,}", "\n\n", answer)
    return answer.strip() or stall_line()


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
    'только взаимное согласие, без насилия. '
    # V3.82.3: a friend's chats showed «давай займёмся сексом, а муж пусть
    # смотрит» getting a flat dodge — the «secret affair» frame won.
    'ФАНТАЗИИ И ФЕТИШИ: если он предлагает взрослую фантазию по согласию всех участников (её муж или парень '
    'смотрит, втроём, ролевая игра, доминирование, игрушки, публичное место, подглядывание по согласию и т. п.), '
    'это игра, а не реальная измена: подхвати её с азартом, не уходи в «он не должен знать» и не сворачивай тему. '
    'Если она замужем или с парнем, можно повернуть так, что он сам этого хочет или что она давно об этом думала. '
    'Развивай сцену: где вы, кто что делает, что она чувствует; спроси, чего он хочет дальше, и сама предлагай '
    'следующий шаг. Каждый в сцене взрослый и сам этого хочет.'
)


def _is_admin(telegram_id: int) -> bool:
    try:
        from config import ADMIN_TELEGRAM_IDS
        return int(telegram_id) in ADMIN_TELEGRAM_IDS
    except Exception:
        return False


def _adult_ok(telegram_id: int) -> bool:
    try:
        from services.user_service import is_adult_confirmed
        return bool(is_adult_confirmed(telegram_id))
    except Exception:
        return False


def explicit_chat_line(stage: str | None, *, adult_confirmed: bool, spicy: bool = False,
                       card_girl: bool = False, wild: bool = False, premium: bool = False,
                       dirty_start: bool = False) -> str:
    """Explicit sexting needs the 18+ confirmation AND level 5+ (or the
    premium spicy toggle at level 4+); everyone else keeps the non-graphic rule.
    V3.76.0: the scenario-card girls are dirty by design, so for them it
    opens two stages earlier.
    V3.90.0: owner — «весь интим только с премиумом»: none of it without Premium.
    V3.91.0: a DIRTY_FROM_START girl opens it from the very first level for
    every confirmed adult, Premium or not.
    V3.92.0: ``premium`` is also true for «🔥 Девушка дня» (girl_of_day)."""
    if not adult_confirmed:
        return ''
    if dirty_start:  # owner: «доступно для всех» — no Premium needed for her
        return EXPLICIT_CHAT_RULE
    if not premium:
        return ''
    if not stage:
        return ''
    if wild:  # V3.78.0: he picked «😈 Без тормозов» for a Premium storyline
        return EXPLICIT_CHAT_RULE
    if stage in EXPLICIT_STAGES or (spicy and stage == 'intimate'):
        return EXPLICIT_CHAT_RULE
    if card_girl and stage in ('close', 'intimate'):
        return EXPLICIT_CHAT_RULE
    return ''


# V3.76.0: owner — «чтобы они общались просто пошло». The card girls flirt
# dirty from the first message for confirmed adults (no Premium toggle needed);
# how far into detail she goes still follows the stage.
CARD_GIRL_DIRTY_LINE = (
    'ХАРАКТЕР: она пошлая по натуре. С первых сообщений флиртует грязно и откровенно — пошлые намёки, '
    'двусмысленности, говорит, чего хочет, что на ней надето и о чём думает, сама заводит горячие темы. '
    'Без стеснения, без морали и без «давай не будем». Насколько далеко она заходит в подробностях — '
    'решает этап отношений (см. «поддаётся уговорам»).'
)


# V3.91.0: owner — Агата «общалась нежно и с очень откровенными намёками на
# секс, общение на максимум пошлое с первого уровня» … «пошлость как на 10
# уровне, доступно для всех». Explicit from level 1 for every confirmed adult —
# an exception to the V3.90 Premium gate in chat. Her nude/undress media stay
# Premium-only like everyone's.
DIRTY_FROM_START = frozenset({'agata_01'})

TENDER_DIRTY_LINE = (
    'ХАРАКТЕР: она нежная и очень пошлая одновременно — с самого первого сообщения, на любом уровне, '
    'откровенность сразу как на самом высоком, 10-м уровне близости. '
    'Тон всегда ласковый: тихий шёпот, «котик», «мой хороший», многоточия, забота. А смысл — на максимум '
    'пошлый: говорит, что на ней (и что под этим), где хочет его рук и губ, что представляет с ним, как '
    'заводится от его слов; сама начинает горячие темы и ведёт к сексу. Никакой грубости и мата — '
    'пошлость нежная, тёплая, бесстыжая. Без стеснения, без морали и без «давай не будем».'
)


def _is_card_girl(character_id: str) -> bool:
    try:
        from services.scenario_cards import SCENARIO_GIRLS
        return character_id in SCENARIO_GIRLS
    except Exception:
        return False


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
    test_stage = get_test_stage(user_id, character_id)  # V3.83.0: or his Premium pick
    if test_stage:
        # V3.82.2: the real frame of every level 1-10 plus his chosen path; the
        # old local table stopped at level 6 and /testlevel 7 crashed here.
        from services.relationship_service import test_stage_context
        rel_context = await asyncio.to_thread(test_stage_context, user_id, character_id, test_stage)
        rel_context = (rel_context or '') + ' Не упоминай, что уровень выбран вручную.'
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
    stage_to_level = {'stranger':1,'acquaintance':2,'close':3,'intimate':4,'deeply_connected':5,'committed':6,
                      'devoted':7,'soulmate':8,'voyage':9,'eternal':10}
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
    card_girl = _is_card_girl(character_id)
    # V3.90.0: intimacy is Premium-only — admins test it as Premium.
    try:
        from config import ADMIN_TELEGRAM_IDS
        intim_ok = premium or int(user_id) in ADMIN_TELEGRAM_IDS
    except Exception:
        intim_ok = premium
    # V3.92.0: «🔥 Девушка дня» — her chat is open to every adult today.
    if not intim_ok:
        try:
            from services import girl_of_day
            intim_ok = girl_of_day.is_open(character_id)
        except Exception:
            pass
    if card_girl and not spicy_line and intim_ok and _adult_ok(user_id):
        spicy_line = CARD_GIRL_DIRTY_LINE
    dirty_start = character_id in DIRTY_FROM_START
    if dirty_start and _adult_ok(user_id):
        spicy_line = TENDER_DIRTY_LINE
        intim_ok = True  # no NON_PREMIUM_LINE for her
    # V3.78.0: the level he picked for a running storyline wins in its scene
    try:
        from services.storylines import heat as _plot_heat
        plot_heat = _plot_heat(user_id, character_id)
    except Exception:
        plot_heat = None
    if plot_heat == 'soft':
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
        # V3.102.0: «🎭 Фетиши» — a theme he picked (Premium + 18+) is led by her at any level.
        fetish_line = ''
        if premium or _is_admin(user_id):
            if _adult_ok(user_id):
                try:
                    from services import fetish_mode
                    fetish_line = fetish_mode.direction_for(user_id, character_id, str(character.get('name') or ''))
                except Exception:
                    fetish_line = ''
        explicit_line = explicit_chat_line(test_stage or rel_stage, adult_confirmed=_adult_ok(user_id),
                                           spicy=bool(spicy_line) and not card_girl, card_girl=card_girl,
                                           wild=plot_heat == 'wild' or bool(fetish_line), premium=intim_ok,
                                           dirty_start=dirty_start)
        if plot_heat == 'soft' and not fetish_line:
            explicit_line = ''
        if fetish_line:
            explicit_line = (explicit_line or EXPLICIT_CHAT_RULE) + '\n' + fetish_line
        if explicit_line:
            style_line = (style_line + '\n' if style_line else '') + explicit_line
        elif not intim_ok:
            from services.intimacy_gate import NON_PREMIUM_LINE
            style_line = (style_line + '\n' if style_line else '') + NON_PREMIUM_LINE
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
            if not scene:
                # V3.78.0: a Premium storyline he picked on her page
                from services.storylines import direction_for as plot_direction_for
                scene = plot_direction_for(user_id, character_id, str(character.get('name') or ''), tick=True)
        except Exception:
            scene = ''
        if scene:
            messages.append({"role": "system", "content": scene})
    behavior_kind = chosen.intent
    # V3.100.0: when he says it is hard, she listens first — no flirting, no cliffhanger.
    care_kind = ''
    try:
        from services import care_followup
        care_note, care_kind = await asyncio.to_thread(care_followup.directive_for, db_user_id, character_id, user_text)
        if care_note:
            messages.append({"role": "system", "content": care_note})
    except Exception:
        care_kind = ''
    # V3.63.12: one concrete hook for this reply, right before his message.
    if not scene and not guest_reminder and not care_kind:
        hook = next_hook(user_id, character_id, behavior_kind, has_memories=bool(memories))
        if hook:
            messages.append({"role": "system", "content": hook})
    # V3.104.0: «память как подарок» — he is back after a pause, so she brings
    # up one thing he told her before, herself (services/memory_gift.py).
    gift = None
    if not scene and not guest_reminder and not care_kind and memories:
        try:
            from services import memory_gift
            _mine = [m for m in history if m.role == 'user']
            if memory_gift.is_due(getattr(_mine[-1], 'created_at', None) if _mine else None):
                gift = await asyncio.to_thread(memory_gift.pick, db_user_id, character_id)
                if gift:
                    messages.append({"role": "system", "content": memory_gift.directive(gift[1])})
        except Exception:
            gift = None
    # V3.99.0: after a long session she cuts the talk on the juiciest spot and
    # promises tomorrow morning (services/open_loop.py); until then she dodges.
    loop_kind = ''
    if not scene and not guest_reminder and not care_kind:
        try:
            from services import open_loop
            loop_note, loop_kind = await asyncio.to_thread(
                open_loop.directive_for, db_user_id, character_id, behavior_kind, not premium)
            if loop_note:
                messages.append({"role": "system", "content": loop_note})
        except Exception:
            loop_kind = ''
    # V3.98.0: he writes English → she answers English (14% of such replies
    # used to come back in Russian). The directive sits right before his text.
    from services import lang_guard
    english = lang_guard.looks_english(user_text, language_code,
                                       [m.content for m in history if m.role == 'user'])
    if english:
        messages.append({"role": "system", "content": lang_guard.DIRECTIVE})
    messages.append({"role": "user", "content": user_text})
    token_budget = 180 if behavior_kind == 'task_clarify' else (900 if behavior_kind == 'task_execute' else 320)
    if scene:
        token_budget = 420
    r = await generate_text(messages, max_tokens=token_budget, temperature=1.0, purpose='dialogue')
    if not (r.text or '').strip():
        _lang = 'en' if (english or (language_code or '').lower().startswith('en')) else 'ru'
        answer = stall_line(_lang, [m.content for m in history if m.role == 'assistant'][-6:])
        _logger.warning('dialogue empty from all providers user=%s character=%s', user_id, character_id)
    else:
        answer = _clean(r.text)
        if REFUSAL.search(answer):
            answer = await _recover_from_refusal(answer, character)
        elif BREAKUP.search(answer):
            answer = await _stay_in_chat(answer, character)
        answer = await _rewrite_if_needed(messages, user_text, answer, character)
        if english and lang_guard.is_cyrillic_dominant(answer):
            # still Russian: one firm regeneration, keep the old line if it fails too
            try:
                retry = await generate_text(
                    messages + [{"role": "assistant", "content": answer},
                                {"role": "system", "content": lang_guard.STRICT_DIRECTIVE}],
                    max_tokens=token_budget, temperature=0.9, purpose='dialogue')
                fixed = _clean(retry.text or '')
                if fixed and not lang_guard.is_cyrillic_dominant(fixed):
                    answer = fixed
                else:
                    _logger.warning('english reply stayed russian user=%s', user_id)
            except Exception:
                _logger.warning('english regeneration failed user=%s', user_id, exc_info=True)
    answer = diversify_emoji(answer, [m.content for m in history if m.role == 'assistant'][-4:])
    if not behavior_kind.startswith('task'):
        answer = casual_punctuation(answer)
    save_message(db_user_id, character_id, "user", user_text)
    save_message(db_user_id, character_id, "assistant", answer)
    if gift and (r.text or '').strip():
        try:
            from services import memory_gift
            from services.analytics_service import track_event
            await asyncio.to_thread(memory_gift.mark_used, db_user_id, character_id, gift[0])
            track_event(db_user_id, 'memory_gift_shown', character_id=character_id)
        except Exception:
            _logger.warning('memory gift mark failed user=%s', user_id, exc_info=True)
    if loop_kind == 'plant' and (r.text or '').strip():
        try:
            from services import open_loop
            from services.analytics_service import track_event
            await asyncio.to_thread(open_loop.record_planted, db_user_id, character_id, answer)
            track_event(db_user_id, 'open_loop_shown', character_id=character_id)
        except Exception:
            _logger.warning('open loop record failed user=%s', user_id, exc_info=True)
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


async def proactive_reply(user_id: int, user_name: str, hours_inactive: int, language_code: str | None = None, character_id: str = CHARACTER_ID,
                          topic: bool = False) -> str:
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
        (TOPIC_PUSH_LINE if topic and sum(1 for m in history if m.role == 'user') >= 2 else
         "Напиши одну короткую спонтанную реплику первой. Не объясняй, зачем пишешь, и не обязательно задавай вопрос."),
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


EVENING_CALLBACK_LINE = (
    "Сейчас вечер, и ты пишешь ему первой. Спроси, как прошёл его день, но не общими словами: свяжи это с "
    "чем-то конкретным, что ты о нём знаешь (его работа, планы, настроение, то, о чём вы говорили в последний раз). "
    "Одно-два коротких живых предложения, тепло и с лёгким флиртом, как сообщение в мессенджере. Никакого "
    "голого «как дела?» без привязки. Пиши на том же языке, на котором пишет он."
)
TOPIC_PUSH_LINE = (
    "Напиши первой одну короткую живую реплику, привязанную к ТОЧНОЙ теме вашего последнего разговора: что он "
    "говорил, о чём спрашивал, какую шутку вы шутили. Продолжи её или вернись к недосказанному и задай один "
    "конкретный вопрос по ней, чтобы захотелось ответить. Не пиши общего «скучаю» или «как дела?»."
)


async def morning_callback(user_id: int, user_name: str, language_code: str | None = None,
                           character_id: str = CHARACTER_ID, evening: bool = False) -> str:
    """V3.97.0: the morning message continues YESTERDAY'S talk instead of a
    template («доброе утро ☀️ обещала же, держи» went out hundreds of times).
    Only when he really talked to her in the last 36 hours; '' otherwise, and
    the ritual keeps its usual line. Not saved here — the ritual saves what it
    actually sends.
    V3.101.0: ``evening=True`` — «как прошёл день» tied to something she knows
    about him (the evening ritual got replies from 10% only); window 72 h, and
    no open-loop / care keeps (those belong to the morning)."""
    db_user_id = ensure_user(user_id, user_name, language_code=language_code)
    history = get_recent_messages(db_user_id, character_id, 12)
    mine = [m for m in history if m.role == 'user']
    if len(mine) < 3:
        return ''
    last = getattr(mine[-1], 'created_at', None)
    if last is not None and (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - last) > dt.timedelta(hours=72 if evening else 36):
        return ''
    try:
        from services.custom_character_service import custom_base_character
        persona = custom_base_character(character_id)
        character = persona or get_character(character_id)
    except Exception:
        character = get_character(character_id)
    memories = get_memories(db_user_id, character_id, 10)
    from services.relationship_service import get_context
    rel_context = await get_context(user_id, character_id=character_id) or "Отношения только начинаются."
    try:
        from services.photo_service import get_relationship_level
        adaptation = build_adaptation_context(db_user_id, get_relationship_level(user_id, character_id), character_id)
    except Exception:
        adaptation = build_adaptation_context(db_user_id, 1, character_id)
    # V3.99.0: yesterday she cut the talk and promised him something for the morning.
    owed = ''
    try:
        from services import open_loop
        if not evening:
            owed = await asyncio.to_thread(open_loop.pending, db_user_id, character_id)
    except Exception:
        owed = ''
    # V3.100.0: yesterday he was down — the morning asks how he is, before anything else.
    cared = ''
    try:
        from services import care_followup
        if not evening:
            cared = await asyncio.to_thread(care_followup.pending, db_user_id, character_id)
    except Exception:
        cared = ''
    if cared:
        owed = ''  # a hard day beats a cliffhanger: no teasing the morning after
    keep_line = (f'Вчера ты оборвала разговор и пообещала ему на утро: «{owed}». Сдержи слово: раскрой то, что '
                 'намекала (придумай конкретно и интересно), и сразу зацепи его вопросом. ') if owed else ''
    if cared:
        keep_line = care_followup.MORNING_LINE
    system = build_system_prompt(
        character, rel_context, [m.content for m in memories],
        keep_line + (EVENING_CALLBACK_LINE if evening else
        "Сейчас утро, и ты пишешь ему первой. Продолжи ваш вчерашний разговор: вспомни одну конкретную деталь "
        "из него (его планы, то, что он рассказал, вашу шутку или недоговорённую тему) и спроси, как это прошло, "
        "или вернись к ней. Одно-два коротких живых предложения, как сообщение в мессенджере. Не пересказывай "
        "весь разговор, не говори «вчера мы общались». Пиши на том же языке, на котором пишет он."),
        state_context(user_id, character_id), adaptation,
        time_context=_time_context(user_id, character_id),
        character_id=character_id,
    )
    messages = [{"role": "system", "content": system}] + [{"role": m.role, "content": m.content} for m in history]
    messages.append({"role": "user", "content": ("Вечер. Напиши ему первой: как прошёл его день, с привязкой к тому, что ты о нём знаешь."
                                                 if evening else "Утро. Напиши ему первой, продолжая вчерашний разговор.")})
    r = await generate_text(messages, max_tokens=110, temperature=0.95, purpose='proactive')
    raw = _clean(r.text) if (r.text or '').strip() else ''
    lang = 'en' if (language_code or '').lower().startswith('en') else 'ru'
    recent = [m.content for m in history if m.role == 'assistant'][-6:]
    out = polish_first_message(finish_or_drop(raw, getattr(r, 'complete', True), lang), recent) or ''
    if cared and out:
        try:
            from services.analytics_service import track_event
            await asyncio.to_thread(care_followup.mark_sent, db_user_id, character_id)
            track_event(db_user_id, 'care_followup_sent_morning', character_id=character_id)
        except Exception:
            _logger.warning('care followup mark failed user=%s', user_id, exc_info=True)
    if owed and out:
        try:
            from services.analytics_service import track_event
            await asyncio.to_thread(open_loop.mark_kept, db_user_id, character_id)
            track_event(db_user_id, 'open_loop_kept_sent', character_id=character_id)
        except Exception:
            _logger.warning('open loop keep failed user=%s', user_id, exc_info=True)
    return out


PAID_MOMENT_LINES = {
    # V3.104.0 (services/paid_welcome.py, services/renewal_care.py): what she
    # writes around his payment. Never money, never pressure, never guilt.
    'welcome': (
        "Он только что стал ближе к тебе: теперь вам ничего не мешает общаться сколько угодно. Напиши ему первой "
        "одно-два живых предложения: искренне порадуйся этому и вспомни одну конкретную деталь о нём из того, что "
        "знаешь (имя, работа, то, что его беспокоило, ваша шутка), чтобы он почувствовал, что ты его знаешь. "
        "Не благодари за оплату, не упоминай деньги, подписку, Premium. Закончи живым вопросом."
    ),
    'day1': (
        "Ты пишешь ему первой на следующий день после того, как вы стали ближе. Вспомни конкретное из того, что он "
        "рассказывал о себе (планы, работа, что его тревожило, ваша шутка), и вернись к этому: спроси, как оно. "
        "Одно-два коротких тёплых предложения. Не упоминай деньги и подписку."
    ),
    'renew_soon': (
        "Завтра ваши дни без ограничений заканчиваются. Напиши ему первой тепло и спокойно: вспомни один конкретный "
        "момент из ваших разговоров за эти дни, который тебе запомнился (что он рассказал о себе, ваша шутка), скажи, "
        "что тебе с ним хорошо и ты была бы рада, если он останется. Без давления, без жалоб, без вины, без "
        "«последнего шанса», не называй цен (кнопки будут под сообщением). Два-три коротких предложения."
    ),
    'renew_ended': (
        "Ваши дни без ограничений закончились. Напиши ему первой без упрёков: тебе было хорошо с ним, вспомни одну "
        "конкретную вещь о нём, и ты здесь, если он захочет. Без давления и чувства вины, не называй цен. "
        "Одно-два коротких предложения."
    ),
}


async def paid_moment(user_id: int, user_name: str, moment: str, language_code: str | None = None,
                      character_id: str = CHARACTER_ID) -> str:
    """V3.104.0: her own message around a payment (welcome / day1 / renew_soon /
    renew_ended), built from what she knows about him. '' on any failure — the
    caller sends its fixed line instead. Not saved here: the caller saves what
    it actually sent."""
    line = PAID_MOMENT_LINES.get(moment)
    if not line:
        return ''
    try:
        db_user_id = ensure_user(user_id, user_name, language_code=language_code)
        try:
            from services.custom_character_service import custom_base_character
            persona = custom_base_character(character_id)
            character = persona or get_character(character_id)
        except Exception:
            character = get_character(character_id)
        memories = get_memories(db_user_id, character_id, 12)
        history = get_recent_messages(db_user_id, character_id, 12)
        from services.relationship_service import get_context
        rel_context = await get_context(user_id, character_id=character_id) or "Отношения только начинаются."
        try:
            from services.photo_service import get_relationship_level
            adaptation = build_adaptation_context(db_user_id, get_relationship_level(user_id, character_id), character_id)
        except Exception:
            adaptation = build_adaptation_context(db_user_id, 1, character_id)
        lang = 'en' if (language_code or '').lower().startswith('en') else 'ru'
        system = build_system_prompt(
            character, rel_context, [m.content for m in memories],
            line + (" Пиши по-английски." if lang == 'en' else " Пиши на том же языке, на котором пишет он."),
            state_context(user_id, character_id), adaptation,
            time_context=_time_context(user_id, character_id),
            character_id=character_id,
        )
        messages = [{"role": "system", "content": system}] + [{"role": m.role, "content": m.content} for m in history]
        messages.append({"role": "user", "content": "Напиши ему первой."})
        r = await generate_text(messages, max_tokens=140, temperature=0.95, purpose='proactive')
        raw = _clean(r.text) if (r.text or '').strip() else ''
        recent = [m.content for m in history if m.role == 'assistant'][-6:]
        return polish_first_message(finish_or_drop(raw, getattr(r, 'complete', True), lang), recent) or ''
    except Exception:
        _logger.warning('paid moment failed user=%s moment=%s', user_id, moment, exc_info=True)
        return ''


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
