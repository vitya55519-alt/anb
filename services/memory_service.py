import json
import re
from datetime import datetime, timezone
from sqlalchemy import select, delete
from services.db import SessionLocal
from models.app_models import Memory, Message, User
from config import AI_KEY, AI_MODEL, AI_BASE_URL
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=AI_KEY, base_url=AI_BASE_URL)


def save_message(user_id, character_id, role, content):
    with SessionLocal() as s:
        s.add(Message(user_id=user_id, character_id=character_id, role=role, content=content))
        if role == "user":
            user = s.get(User, user_id)
            if user:
                user.last_active_at = datetime.now(timezone.utc).replace(tzinfo=None)
        s.commit()


def get_recent_messages(user_id, character_id, limit=20):
    with SessionLocal() as s:
        rows = s.scalars(select(Message).where(
            Message.user_id == user_id, Message.character_id == character_id
        ).order_by(Message.created_at.desc()).limit(limit)).all()
        return list(reversed(rows))


def get_memories(user_id, character_id, limit=20):
    with SessionLocal() as s:
        return s.scalars(select(Memory).where(
            Memory.user_id == user_id, Memory.character_id == character_id
        ).order_by(Memory.importance.desc(), Memory.updated_at.desc()).limit(limit)).all()


def delete_memories(user_id, character_id):
    with SessionLocal() as s:
        s.execute(delete(Memory).where(Memory.user_id == user_id, Memory.character_id == character_id))
        s.commit()


def _extract_json(text):
    match = re.search(r'\{.*\}', text or '', re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def extract_memory(user_id: int, character_id: str, user_text: str):
    if not AI_KEY or len(user_text) < 8:
        return
    prompt = '''Extract only durable, user-provided facts worth remembering for future conversations. Do not store passwords, payment data, exact addresses, health diagnoses, sexual history, political/religious identity, or other highly sensitive data. Return JSON only: {"memories":[{"key":"...","content":"...","confidence":0.0,"importance":0.0}]}. If none, return {"memories":[]}.'''
    try:
        r = await client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role":"system","content":prompt}, {"role":"user","content":user_text}],
            temperature=0,
            max_tokens=250,
        )
        data = _extract_json(r.choices[0].message.content)
        if not data:
            return
        with SessionLocal() as s:
            for item in data.get("memories", [])[:3]:
                key = str(item.get("key", "")).strip()[:128]
                content = str(item.get("content", "")).strip()
                if not key or not content:
                    continue
                conf = max(0.0, min(1.0, float(item.get("confidence", 0.7))))
                imp = max(0.0, min(1.0, float(item.get("importance", 0.5))))
                existing = s.scalar(select(Memory).where(
                    Memory.user_id == user_id, Memory.character_id == character_id, Memory.memory_key == key
                ))
                if existing:
                    existing.content, existing.confidence, existing.importance = content, conf, imp
                    existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                else:
                    s.add(Memory(user_id=user_id, character_id=character_id, memory_key=key,
                                 content=content, confidence=conf, importance=imp))
            s.commit()
    except Exception:
        return
