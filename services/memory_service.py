import json, re
from datetime import datetime, timezone
from sqlalchemy import select, delete
from services.db import SessionLocal
from models.app_models import Memory, Message, User, CommunicationProfile
from config import CHARACTER_ID
from services.llm_provider_service import generate_text

def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)

def save_message(user_id, character_id, role, content, media_kind=None, media_url=None, draft_text=None, image_prompt=None):
    """Store one chat line and return its id. V3.152.0: `draft_text` is the
    erased draft of THIS answer — paid text, kept out of `content` so neither
    the history endpoint nor the prompt can ship it to him for free.
    V3.156.0: `image_prompt` is the paid live photo this line teases — the
    English scene never reaches the client, only the plate that offers it."""
    with SessionLocal() as s:
        row = Message(user_id=user_id, character_id=character_id, role=role, content=content,
                      media_kind=media_kind, media_url=media_url, draft_text=draft_text,
                      image_prompt=image_prompt)
        s.add(row)
        if role == "user":
            user=s.get(User,user_id)
            if user: user.last_active_at=_now()
        s.commit()
        return row.id

def get_recent_messages(user_id, character_id, limit=20):
    with SessionLocal() as s:
        rows=s.scalars(select(Message).where(Message.user_id==user_id,Message.character_id==character_id).order_by(Message.created_at.desc()).limit(limit)).all()
        return list(reversed(rows))

def get_memories(user_id, character_id, limit=20):
    with SessionLocal() as s:
        return s.scalars(select(Memory).where(Memory.user_id==user_id,Memory.character_id==character_id).order_by(Memory.importance.desc(),Memory.updated_at.desc()).limit(limit)).all()

def reset_conversation(user_id:int, character_id:str):
    with SessionLocal() as s:
        s.execute(delete(Message).where(Message.user_id==user_id,Message.character_id==character_id))
        s.execute(delete(Memory).where(Memory.user_id==user_id,Memory.character_id==character_id))
        s.execute(delete(CommunicationProfile).where(CommunicationProfile.user_id==user_id,CommunicationProfile.character_id==character_id))
        s.commit()

def _extract_json(text):
    m=re.search(r'\{.*\}', text or '', re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except json.JSONDecodeError: return None

_EXTRACT_PROMPT_OLD='''Извлеки только устойчивые факты, которые пользователь сам сообщил и которые реально пригодятся в будущей переписке: предпочтения, важные планы, обещания, повторяющиеся темы, внутренние шутки. Не сохраняй пароли, платёжные данные, точные адреса, медицинские диагнозы, сексуальную историю, политические/религиозные убеждения и другие особо чувствительные данные. Верни только JSON: {"memories":[{"key":"...","content":"...","confidence":0.0,"importance":0.0,"type":"fact|preference|promise|inside_joke|pending"}]}. Если запоминать нечего: {"memories":[]}.'''
_EXTRACT_PROMPT_V3104='''Извлеки только устойчивые факты, которые пользователь сам сообщил о себе и которые реально пригодятся в будущей переписке. В первую очередь: как его зовут (key "name", importance 0.9), работа или учёба (key "work"), близкие люди и питомцы (type "person"), что его сейчас беспокоит или расстраивает (type "worry", без диагнозов), предстоящие события и планы с указанием когда, если он сказал (type "pending": экзамен, собеседование, поездка, встреча), увлечения и предпочтения, обещания, внутренние шутки. Пиши content коротко, от третьего лица, своими словами (например: "в пятницу у него собеседование в банке"). Не сохраняй пароли, платёжные данные, точные адреса, медицинские диагнозы, сексуальную историю, политические/религиозные убеждения и другие особо чувствительные данные. Верни только JSON: {"memories":[{"key":"...","content":"...","confidence":0.0,"importance":0.0,"type":"fact|preference|promise|inside_joke|pending|worry|person"}]}. Если запоминать нечего: {"memories":[]}.'''

async def extract_memory(user_id:int, character_id:str, user_text:str):
    if len(user_text.strip()) < 12: return
    # V3.104.0 («память как подарок»): his name, work, close people, worries and
    # upcoming events are asked for by name — she brings them up herself later
    # (services/memory_gift.py), so they need clear keys and a «when».
    from services import memory_gift
    prompt=_EXTRACT_PROMPT_V3104 if memory_gift.ENABLED else _EXTRACT_PROMPT_OLD
    try:
        r = await generate_text(
            messages=[{"role":"system","content":prompt},{"role":"user","content":user_text}],
            max_tokens=240,
            temperature=0,
            purpose='memory_extraction',
        )
        data=_extract_json(r.text)
        if not data: return
        with SessionLocal() as s:
            for item in data.get('memories',[])[:3]:
                key=str(item.get('key','')).strip()[:128]; content=str(item.get('content','')).strip()
                if not key or not content: continue
                row=s.scalar(select(Memory).where(Memory.user_id==user_id,Memory.character_id==character_id,Memory.memory_key==key))
                if not row:
                    row=Memory(user_id=user_id,character_id=character_id,memory_key=key,content=content)
                    s.add(row)
                row.content=content; row.memory_type=str(item.get('type','fact'))[:32]
                row.confidence=max(0,min(1,float(item.get('confidence',.7))))
                row.importance=max(0,min(1,float(item.get('importance',.5))))
                row.updated_at=_now()
            s.commit()
    except Exception:
        return
