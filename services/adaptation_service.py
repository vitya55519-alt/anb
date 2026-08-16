from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone

from sqlalchemy import select

from config import CHARACTER_ID, ADAPTATION_ENABLED, ADAPTATION_ANALYZE_EVERY, ADAPTATION_MAX_EXPRESSIONS
from models.app_models import CommunicationProfile, Message
from services.db import SessionLocal
from services.llm_provider_service import generate_text

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_JA_RE = re.compile(r"[\u3040-\u30ff]")
_KO_RE = re.compile(r"[\uac00-\ud7af]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9']{2,24}")

# Stopwords are only used for local candidate counting. The LLM decides which
# recurring expressions are actually slang and safe to mirror.
_STOPWORDS = {
    'это','как','что','так','там','тут','вот','мне','тебе','тебя','меня','она','они','его','еще','ещё','уже','для','или','если','просто','тоже','очень','можно','надо','хочу','хочешь','будет','был','была','есть','нет','да','ну','мы','вы','ты','я','и','а','но','не','на','в','во','по','с','со','к','из','за','же','бы',
    'the','and','you','that','this','with','for','are','was','have','has','not','but','just','what','when','where','why','how','can','could','would','should','your','youre','im','i','me','my','we','they','it','is','to','of','in','on','at','a','an',
}
_SLANG_HINTS = re.compile(r"\b(го|хз|имба|жиза|кринж|рофл|лол|ахах+|дак|ща|чё|че|бля|блин|кайф|топ|норм|жесть|bro|bruh|lol|lmao|idk|imo|ngl|fr|tbh|wtf)\b", re.I)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _load_json(raw: str | None, fallback):
    try:
        value = json.loads(raw or '')
        return value if isinstance(value, type(fallback)) else fallback
    except Exception:
        return fallback


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def detect_language(text: str) -> tuple[str, float]:
    text = text or ''
    low = f' {text.lower()} '
    if _JA_RE.search(text):
        return 'ja', 0.96
    if _KO_RE.search(text):
        return 'ko', 0.96
    cyr = len(_CYRILLIC_RE.findall(text))
    cjk = len(_CJK_RE.findall(text))
    lat = len(_LATIN_RE.findall(text))
    total = max(1, cyr + cjk + lat)
    if cjk >= max(cyr, lat) and cjk >= 2:
        return 'zh', min(0.99, 0.55 + cjk / total * 0.44)
    if cyr >= max(cjk, lat) and cyr >= 2:
        if any(ch in low for ch in ('і','ї','є','ґ')):
            return 'uk', 0.90
        return 'ru', min(0.99, 0.55 + cyr / total * 0.44)
    if lat >= 2:
        markers = {
            'es': (' hola ', ' gracias ', ' cómo ', ' como ', ' estoy ', ' para ', ' pero ', ' quiero '),
            'de': (' hallo ', ' danke ', ' ich ', ' nicht ', ' wie ', ' und ', ' bitte '),
            'fr': (' bonjour ', ' merci ', ' je ', ' suis ', ' avec ', ' pourquoi ', ' comment '),
            'it': (' ciao ', ' grazie ', ' sono ', ' non ', ' come ', ' perché ', ' perche '),
            'pt': (' olá ', ' ola ', ' obrigado ', ' obrigada ', ' você ', ' voce ', ' não ', ' nao '),
        }
        scores = {lang: sum(1 for m in ms if m in low) for lang, ms in markers.items()}
        best = max(scores, key=scores.get)
        if scores[best] >= 1:
            return best, min(0.95, 0.72 + 0.07 * scores[best])
        return 'en', min(0.95, 0.50 + lat / total * 0.40)
    return 'auto', 0.20


def _rolling(old: float, value: float, n_before: int) -> float:
    # Recent behaviour matters, but one message must never rewrite the whole profile.
    alpha = 0.18 if n_before >= 5 else 1.0 / max(1, n_before + 1)
    return float(old) * (1.0 - alpha) + float(value) * alpha


def observe_message(user_id: int, text: str, character_id: str = CHARACTER_ID) -> None:
    """Cheap local observation on every user message.

    This does not let the model rewrite itself. It only updates a bounded profile
    that later becomes soft context for Anna's replies.
    """
    if not ADAPTATION_ENABLED:
        return
    clean = (text or '').strip()
    if not clean:
        return
    lang, lang_conf = detect_language(clean)
    letters = [c for c in clean if c.isalpha()]
    uppercase = sum(1 for c in letters if c.isupper()) / max(1, len(letters))
    emoji = min(1.0, len(_EMOJI_RE.findall(clean)) / max(1, len(clean) / 24))
    question = 1.0 if '?' in clean or '？' in clean else 0.0
    slang_hint = 1.0 if _SLANG_HINTS.search(clean) else 0.0
    tokens = [t.lower() for t in _TOKEN_RE.findall(clean)]

    with SessionLocal() as s:
        row = s.scalar(select(CommunicationProfile).where(
            CommunicationProfile.user_id == user_id,
            CommunicationProfile.character_id == character_id,
        ))
        if not row:
            row = CommunicationProfile(user_id=user_id, character_id=character_id)
            s.add(row)
            s.flush()
        n = int(row.message_count or 0)
        row.avg_message_length = _rolling(row.avg_message_length or 0.0, min(len(clean), 1200), n)
        row.emoji_rate = _rolling(row.emoji_rate or 0.0, emoji, n)
        row.question_rate = _rolling(row.question_rate or 0.0, question, n)
        row.uppercase_rate = _rolling(row.uppercase_rate or 0.0, uppercase, n)
        row.slang_level = _rolling(row.slang_level or 0.0, slang_hint, n)
        row.message_count = n + 1
        if lang != 'auto' and (lang_conf >= row.language_confidence * 0.75 or row.preferred_language in ('auto', lang)):
            row.preferred_language = lang
            row.language_confidence = max(float(row.language_confidence or 0.0) * 0.88, lang_conf)

        counts = _load_json(row.token_counts_json, {})
        for token in tokens:
            # Store only likely slang/interjection candidates locally. Novel slang is
            # still discovered by the periodic LLM analysis of recent messages.
            likely_slang = bool(_SLANG_HINTS.fullmatch(token)) or bool(re.search(r'(.)\1{2,}', token))
            if likely_slang and token not in _STOPWORDS and not token.isdigit():
                counts[token] = min(1000, int(counts.get(token, 0)) + 1)
        # Bound storage: keep only the 80 most common recent candidates.
        counts = dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:80])
        row.token_counts_json = json.dumps(counts, ensure_ascii=False)
        row.updated_at = _now()
        s.commit()


def _extract_json(text: str):
    m = re.search(r'\{.*\}', text or '', re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _recent_user_texts(user_id: int, character_id: str, limit: int = 12) -> list[str]:
    with SessionLocal() as s:
        rows = s.scalars(select(Message).where(
            Message.user_id == user_id,
            Message.character_id == character_id,
            Message.role == 'user',
        ).order_by(Message.created_at.desc()).limit(limit)).all()
        return [r.content for r in reversed(rows)]


async def maybe_analyze_profile(user_id: int, character_id: str = CHARACTER_ID) -> None:
    """Use the LLM only every few messages to refine style/slang semantics."""
    if not ADAPTATION_ENABLED:
        return
    with SessionLocal() as s:
        row = s.scalar(select(CommunicationProfile).where(
            CommunicationProfile.user_id == user_id,
            CommunicationProfile.character_id == character_id,
        ))
        if not row or row.message_count < ADAPTATION_ANALYZE_EVERY or row.message_count - row.last_analyzed_count < ADAPTATION_ANALYZE_EVERY:
            return
        message_count = int(row.message_count)
        token_counts = _load_json(row.token_counts_json, {})

    recent = _recent_user_texts(user_id, character_id, 12)
    if not recent:
        return
    repeated_candidates = [k for k, v in token_counts.items() if int(v) >= 2][:25]
    system = '''Ты анализатор манеры общения. Не меняй персонажа и не отвечай пользователю. По сообщениям определи только НЕЧУВСТВИТЕЛЬНЫЕ особенности стиля: язык, формальность, юмор, сарказм, уровень сленга, предпочтительную длину ответа и устойчивые разговорные выражения. Не извлекай здоровье, религию, политику, сексуальную жизнь, точный адрес, финансы, пароли и другие чувствительные данные. Не сохраняй оскорбления по защищаемым признакам как выражения для подражания. Верни ТОЛЬКО JSON вида: {"language":"ISO-639-1 код языка, например ru|en|zh|es|de|fr|it|pt|uk|ja|ko, либо auto","style":{"formality":0.0,"humor":0.0,"sarcasm":0.0,"slang":0.0,"emoji":0.0,"detail":"short|medium|long"},"expressions":[{"text":"...","context":"casual|joking|agreement|surprise|other","confidence":0.0}]}. Максимум 8 expressions. Сохраняй только реально характерные выражения, не обычные слова.'''
    payload = 'Повторяющиеся кандидаты: ' + ', '.join(repeated_candidates) + '\n\nСообщения:\n' + '\n'.join(f'- {x}' for x in recent)
    try:
        r = await generate_text(
            messages=[{'role':'system','content':system},{'role':'user','content':payload}],
            max_tokens=320,
            temperature=0,
            purpose='adaptation_analysis',
        )
        data = _extract_json(r.text)
        if not data:
            return
        with SessionLocal() as s:
            row = s.scalar(select(CommunicationProfile).where(
                CommunicationProfile.user_id == user_id,
                CommunicationProfile.character_id == character_id,
            ))
            if not row:
                return
            lang = str(data.get('language') or 'auto')[:16]
            if re.fullmatch(r'[a-z]{2,3}', lang):
                row.preferred_language = lang
                row.language_confidence = max(float(row.language_confidence or 0), 0.80)

            old_style = _load_json(row.style_json, {})
            new_style = data.get('style') if isinstance(data.get('style'), dict) else {}
            merged = dict(old_style)
            for key in ('formality','humor','sarcasm','slang','emoji'):
                if key in new_style:
                    nv = _clamp(new_style[key])
                    ov = float(old_style.get(key, nv))
                    merged[key] = round(ov * 0.65 + nv * 0.35, 3)
            detail = str(new_style.get('detail') or old_style.get('detail') or 'medium')
            merged['detail'] = detail if detail in {'short','medium','long'} else 'medium'
            row.style_json = json.dumps(merged, ensure_ascii=False)

            old_expr = _load_json(row.slang_json, [])
            by_text = {str(x.get('text','')).lower(): x for x in old_expr if isinstance(x, dict) and x.get('text')}
            for item in (data.get('expressions') or [])[:8]:
                if not isinstance(item, dict):
                    continue
                text = str(item.get('text','')).strip()[:40]
                if len(text) < 2:
                    continue
                key = text.lower()
                conf = _clamp(item.get('confidence', 0.6))
                old = by_text.get(key, {})
                by_text[key] = {
                    'text': text,
                    'context': str(item.get('context') or old.get('context') or 'other')[:20],
                    'confidence': round(max(conf, float(old.get('confidence', 0.0)) * 0.96), 3),
                }
            # Confidence slowly decays for stale expressions; this prevents permanent imitation.
            for key, item in list(by_text.items()):
                item['confidence'] = round(float(item.get('confidence', 0.0)) * 0.985, 3)
                if item['confidence'] < 0.35:
                    by_text.pop(key, None)
            row.slang_json = json.dumps(sorted(by_text.values(), key=lambda x: x['confidence'], reverse=True)[:ADAPTATION_MAX_EXPRESSIONS], ensure_ascii=False)
            decayed_counts = {k: max(1, int(float(v) * 0.90)) for k, v in token_counts.items() if int(v) >= 2}
            row.token_counts_json = json.dumps(dict(sorted(decayed_counts.items(), key=lambda kv: kv[1], reverse=True)[:80]), ensure_ascii=False)
            row.last_analyzed_count = message_count
            row.updated_at = _now()
            s.commit()
    except Exception:
        # Adaptive learning must never break the actual conversation.
        return


def get_profile(user_id: int, character_id: str = CHARACTER_ID):
    with SessionLocal() as s:
        return s.scalar(select(CommunicationProfile).where(
            CommunicationProfile.user_id == user_id,
            CommunicationProfile.character_id == character_id,
        ))


def build_adaptation_context(user_id: int, relationship_level: int = 1, character_id: str = CHARACTER_ID) -> str:
    if not ADAPTATION_ENABLED:
        return 'Персональная адаптация отключена настройкой сервера.'
    row = get_profile(user_id, character_id)
    if not row or row.message_count < 2:
        return 'Пока стиль собеседника ещё неясен. Не пытайся искусственно его копировать.'
    style = _load_json(row.style_json, {})
    expressions = [x for x in _load_json(row.slang_json, []) if isinstance(x, dict) and float(x.get('confidence', 0)) >= 0.58]
    expressions = expressions[:6]
    lang_name = {'ru':'русский','en':'English','zh':'中文','es':'Español','de':'Deutsch','fr':'Français','it':'Italiano','pt':'Português','uk':'Українська','ja':'日本語','ko':'한국어'}.get(row.preferred_language, row.preferred_language if row.preferred_language != 'auto' else 'язык последнего сообщения')
    avg = float(row.avg_message_length or 0)
    local_length = 'короткие' if avg < 55 else ('средние' if avg < 180 else 'развёрнутые')
    adaptation = min(0.42, 0.14 + max(0, relationship_level - 1) * 0.055)
    expr_text = ', '.join(f'«{x.get("text")}»' for x in expressions) if expressions else 'пока нет устойчивых'
    emoji_pref = float(style.get('emoji', row.emoji_rate or 0.35))
    return f'''АДАПТАЦИЯ К СОБЕСЕДНИКУ\n- Основной язык: {lang_name}. Если последнее сообщение явно на другом языке, отвечай на нём.\n- Его обычная длина сообщений: {local_length}.\n- Формальность: {float(style.get('formality', 0.35)):.2f}; юмор: {float(style.get('humor', 0.45)):.2f}; сарказм: {float(style.get('sarcasm', 0.25)):.2f}; сленг: {float(style.get('slang', row.slang_level or 0.25)):.2f}; привычка к эмодзи: {emoji_pref:.2f}.\n- Знакомые выражения: {expr_text}.\n- Эмодзи адаптируй мягко: базовый стиль Анны остаётся немного эмоциональнее собеседника и допускает обычно 1, иногда 2 уместных эмодзи в лёгком сообщении. Если тема серьёзная или техническая, не добавляй их искусственно.\n- Сила адаптации сейчас примерно {adaptation:.2f}: характер Анны всегда сильнее зеркалирования. Иногда естественно используй максимум одно знакомое выражение, только когда подходит контекст. Не копируй опечатки, агрессию, оскорбления и не превращайся в пародию на пользователя. Не упоминай, что анализируешь стиль или ведёшь профиль.'''


def observe_photo_preference(user_id: int, scene: str, clothing: str = '', hairstyle: str = '', location: str = '', character_id: str = CHARACTER_ID) -> None:
    """Learn lightweight visual preferences from actual user photo requests.

    This stores only product preferences (scene/color/hair), not sensitive personal facts.
    """
    if not ADAPTATION_ENABLED:
        return
    with SessionLocal() as db:
        row = db.scalar(select(CommunicationProfile).where(
            CommunicationProfile.user_id == user_id,
            CommunicationProfile.character_id == character_id,
        ))
        if not row:
            row = CommunicationProfile(user_id=user_id, character_id=character_id)
            db.add(row); db.flush()
        data = _load_json(getattr(row, 'visual_json', '{}'), {})
        scenes = data.setdefault('scenes', {})
        scenes[scene] = min(500, int(scenes.get(scene, 0)) + 1)
        if hairstyle:
            hairs = data.setdefault('hairstyles', {})
            hairs[hairstyle] = min(200, int(hairs.get(hairstyle, 0)) + 1)
        low = f'{clothing} {location}'.lower()
        colors = data.setdefault('colors', {})
        for color, markers in {
            'black': ('black','черн'), 'white': ('white','бел'), 'burgundy': ('burgundy','красн'),
            'green': ('green','зел'), 'navy': ('navy','син'), 'pink': ('pink','розов'),
        }.items():
            if any(m in low for m in markers):
                colors[color] = min(200, int(colors.get(color, 0)) + 1)
        # Bound each counter map and gently decay very old tastes.
        for key in ('scenes','hairstyles','colors'):
            bucket = data.get(key, {})
            data[key] = dict(sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)[:12])
        row.visual_json = json.dumps(data, ensure_ascii=False)
        row.updated_at = _now()
        db.commit()


def get_visual_preferences(user_id: int, character_id: str = CHARACTER_ID) -> dict:
    row = get_profile(user_id, character_id)
    return _load_json(getattr(row, 'visual_json', '{}'), {}) if row else {}



def observe_photo_feedback(
    user_id: int,
    liked: bool,
    scene: str,
    clothing: str = '',
    hairstyle: str = '',
    character_id: str = CHARACTER_ID,
) -> None:
    """Weight explicit visual feedback more strongly than an ordinary request.

    Positive feedback boosts recurring choices. Negative feedback gently lowers
    the corresponding counters instead of permanently banning a style.
    """
    if not ADAPTATION_ENABLED:
        return
    with SessionLocal() as db:
        row = db.scalar(select(CommunicationProfile).where(
            CommunicationProfile.user_id == user_id,
            CommunicationProfile.character_id == character_id,
        ))
        if not row:
            row = CommunicationProfile(user_id=user_id, character_id=character_id)
            db.add(row); db.flush()
        data = _load_json(getattr(row, 'visual_json', '{}'), {})
        delta = 3 if liked else -1
        scenes = data.setdefault('scenes', {})
        scenes[scene] = max(0, min(500, int(scenes.get(scene, 0)) + delta))
        if hairstyle:
            hairs = data.setdefault('hairstyles', {})
            hairs[hairstyle] = max(0, min(200, int(hairs.get(hairstyle, 0)) + delta))
        low = clothing.lower()
        colors = data.setdefault('colors', {})
        for color, markers in {
            'black': ('black','черн'), 'white': ('white','бел'), 'burgundy': ('burgundy','красн'),
            'green': ('green','зел'), 'navy': ('navy','син'), 'pink': ('pink','розов'),
        }.items():
            if any(m in low for m in markers):
                colors[color] = max(0, min(200, int(colors.get(color, 0)) + delta))
        feedback = data.setdefault('feedback', {'likes': 0, 'dislikes': 0})
        key = 'likes' if liked else 'dislikes'
        feedback[key] = int(feedback.get(key, 0)) + 1
        for key2 in ('scenes','hairstyles','colors'):
            bucket = {k:v for k,v in data.get(key2, {}).items() if int(v) > 0}
            data[key2] = dict(sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)[:12])
        row.visual_json = json.dumps(data, ensure_ascii=False)
        row.updated_at = _now()
        db.commit()
