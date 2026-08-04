import json, re
from datetime import datetime, timezone
from sqlalchemy import select, delete
from services.db import SessionLocal
from models.app_models import Memory, Message, User
from config import AI_KEY, AI_MODEL, AI_BASE_URL
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=AI_KEY, base_url=AI_BASE_URL)

def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)

def save_message(user_id, character_id, role, content):
    with SessionLocal() as s:
        s.add(Message(user_id=user_id, character_id=character_id, role=role, content=content))
        if role == "user":
            user=s.get(User,user_id)
            if user: user.last_active_at=_now()
        s.commit()

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
        s.commit()

def _extract_json(text):
    m=re.search(r'\{.*\}', text or '', re.S)
    if not m: return None
    try: return json.loads(m.group(0))
    except json.JSONDecodeError: return None

async def extract_memory(user_id:int, character_id:str, user_text:str):
    if len(user_text.strip()) < 12: return
    prompt='''Извлеки только устойчивые факты, которые пользователь сам сообщил и которые реально пригодятся в будущей переписке: предпочтения, важные планы, обещания, повторяющиеся темы, внутренние шутки. Не сохраняй пароли, платёжные данные, точные адреса, медицинские диагнозы, сексуальную историю, политические/религиозные убеждения и другие особо чувствительные данные. Верни только JSON: {"memories":[{"key":"...","content":"...","confidence":0.0,"importance":0.0,"type":"fact|preference|promise|inside_joke|pending"}]}. Если запоминать нечего: {"memories":[]}.'''
    try:
        r=await client.chat.completions.create(model=AI_MODEL,messages=[{"role":"system","content":prompt},{"role":"user","content":user_text}],temperature=0,max_tokens=240)
        data=_extract_json(r.choices[0].message.content)
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
