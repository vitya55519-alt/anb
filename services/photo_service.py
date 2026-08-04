from __future__ import annotations
import base64, logging, random, re, json
from dataclasses import dataclass
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
from typing import Optional
from aiogram import Bot
from aiogram.types import BufferedInputFile
from openai import AsyncOpenAI
from sqlalchemy import select
from config import CHARACTER_ID, IMAGE_API_KEY, IMAGE_BASE_URL, IMAGE_MODEL, IMAGE_SIZE, IMAGE_QUALITY, FREE_PHOTOS_PER_DAY, PREMIUM_PHOTOS_PER_DAY, PHOTO_COST_STARS
from models.app_models import User
from models.relationship_models import UserCharacterRelationship
from models.photo_models import PhotoDailyUsage, PhotoDelivery, PhotoOffer
from services.db import SessionLocal
from services.character_service import get_anna
from services.test_mode import get_stage as get_test_stage
from services.access_service import is_premium
from services.user_service import ensure_user, get_state, update_state
from services.payments import consume_photo_credit, get_photo_credits

logger=logging.getLogger(__name__)
client=AsyncOpenAI(api_key=IMAGE_API_KEY, base_url=IMAGE_BASE_URL)

SCENES={
 'selfie':'natural smartphone selfie in an ordinary everyday setting',
 'home':'relaxed realistic smartphone photo at home',
 'park':'natural photo during a walk in a green city park',
 'cafe':'natural smartphone photo in a cozy cafe',
 'mirror':'realistic full-body mirror photo in a tidy apartment',
 'outfit':'full-body smartphone photo focused on the outfit',
 'evening':'stylish evening portrait in a tasteful outfit',
 'fashion':'premium fashion-editorial portrait, elegant and non-explicit',
 'lingerie':'tasteful adult lingerie fashion editorial, non-explicit, no nudity or transparent exposure',
}
SCENE_LEVELS={'selfie':1,'home':1,'park':1,'cafe':1,'outfit':1,'mirror':2,'evening':2,'fashion':2,'lingerie':4}
STAGE_INDEX={'stranger':0,'acquaintance':1,'close':2,'intimate':3,'deeply_connected':4,'committed':5}
AUTO_CAPTIONS={
 'selfie':('ладно, держи 😌','вот такая я сейчас','ну всё, поймала нормальный свет 😂'),
 'home':('я сегодня максимально домашняя 😌','вот мой режим на сегодня','да, я реально никуда не собираюсь ахах'),
 'park':('вышла немного пройтись 🌿','смотри какой свет поймала','вот, пока гуляю'),
 'cafe':('кофе спасает ☕','я тут зависла с кофе','вот моё место на ближайшие полчаса'),
 'mirror':('зеркало сегодня не подвело 😏','ну вот, целиком','поймала себя в зеркале'),
 'outfit':('ты же хотел посмотреть образ 😌','вот что выбрала','ну как тебе сегодняшний вариант?'),
 'evening':('сегодня решила выглядеть вот так ✨','вечерний вариант','мне самой этот образ нравится'),
 'fashion':('сегодня у меня настроение на красивый кадр','немного журнального вайба 😌'),
 'lingerie':('сегодня я немного смелее 😏','ладно, этот образ покажу','вот такой fashion-настрой сегодня'),
}

@dataclass(frozen=True)
class GeneratedPhoto:
    url: Optional[str]=None
    data: Optional[bytes]=None

@dataclass(frozen=True)
class PhotoRequest:
    scene:str='selfie'
    clothing:str=''
    hairstyle:str=''
    location:str=''
    angle:str=''
    mood:str='warm, natural'


def _today(): return datetime.now(timezone.utc).date()
def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)

def _user_rel(s, telegram_id:int):
    u=s.scalar(select(User).where(User.telegram_id==str(telegram_id)))
    if not u: return None,None
    r=s.scalar(select(UserCharacterRelationship).where(UserCharacterRelationship.user_id==u.id,UserCharacterRelationship.character_id==CHARACTER_ID))
    return u,r

def get_relationship_stage(telegram_id:int)->str:
    override=get_test_stage(telegram_id)
    if override: return override
    ensure_user(telegram_id)
    with SessionLocal() as s:
        _,r=_user_rel(s,telegram_id); return r.stage if r else 'stranger'

def get_daily_limit(telegram_id:int)->int:
    return PREMIUM_PHOTOS_PER_DAY if is_premium(telegram_id) else FREE_PHOTOS_PER_DAY

def get_usage(telegram_id:int):
    uid=ensure_user(telegram_id)
    with SessionLocal() as s:
        row=s.scalar(select(PhotoDailyUsage).where(PhotoDailyUsage.user_id==uid,PhotoDailyUsage.character_id==CHARACTER_ID,PhotoDailyUsage.usage_date==_today()))
        limit=get_daily_limit(telegram_id)
        return (row.free_used if row else 0,row.paid_used if row else 0,limit)

def has_free_photo(telegram_id:int)->bool:
    used,_,limit=get_usage(telegram_id); return used<limit

def scene_allowed_for_stage(scene:str,stage:str)->bool:
    return STAGE_INDEX.get(stage,0)+1>=SCENE_LEVELS.get(scene,99)

def build_photo_menu(telegram_id:int):
    used,paid,limit=get_usage(telegram_id)
    return {'stage':get_relationship_stage(telegram_id),'free_used':used,'paid_used':paid,'limit':limit,'free_left':max(0,limit-used),'credits':get_photo_credits(telegram_id),'cost':PHOTO_COST_STARS,'premium':is_premium(telegram_id)}

def create_offer(telegram_id:int,request:PhotoRequest,ttl_minutes:int=30):
    uid=ensure_user(telegram_id)
    payload=json.dumps(request.__dict__,ensure_ascii=False)
    with SessionLocal() as s:
        o=PhotoOffer(user_id=uid,character_id=CHARACTER_ID,scene=request.scene,request_json=payload,created_at=_now(),expires_at=_now()+timedelta(minutes=ttl_minutes)); s.add(o); s.commit(); return o.id

def consume_offer(telegram_id:int,offer_id:int):
    uid=ensure_user(telegram_id)
    with SessionLocal() as s:
        o=s.scalar(select(PhotoOffer).where(PhotoOffer.id==offer_id,PhotoOffer.user_id==uid,PhotoOffer.character_id==CHARACTER_ID))
        if not o or o.consumed or o.expires_at<_now(): return None
        o.consumed=True; s.commit()
        if o.request_json:
            try: return PhotoRequest(**json.loads(o.request_json))
            except Exception: pass
        return PhotoRequest(scene=o.scene)

EXPLICIT=re.compile(r'\b(голая|голый|обнаж|без трус|без бель|соски|генитал|вагин|пенис|nude|naked|topless|explicit)\b',re.I)

def parse_photo_request(text:str)->Optional[PhotoRequest]:
    t=(text or '').strip(); low=t.lower()
    direct=any(x in low for x in ('фото','фотку','селфи','покажись','покажи себя','сфоткай','фотограф','photo','selfie'))
    if not direct: return None
    if EXPLICIT.search(low):
        # Keep the request in a safe visual category instead of asking the image model for explicit nudity.
        return PhotoRequest(scene='fashion',clothing='tasteful non-explicit fashion look with full coverage')
    scene='selfie'
    if any(x in low for x in ('парк','гуля','улиц')): scene='park'
    elif any(x in low for x in ('кафе','кофе','ресторан')): scene='cafe'
    elif any(x in low for x in ('зеркал','mirror')): scene='mirror'
    elif any(x in low for x in ('дома','домаш','кровать','диван')): scene='home'
    elif any(x in low for x in ('вечер','ресторан','клуб')): scene='evening'
    elif any(x in low for x in ('бель','lingerie','будуар')): scene='lingerie'
    elif any(x in low for x in ('образ','наряд','одета','одежд','плать','джинс','леггинс')): scene='outfit'
    clothing=''
    clothing_map=[('черн','black outfit'),('бел','white outfit'),('красн','red outfit'),('плать','fitted elegant dress'),('джинс','jeans with a casual top'),('леггинс','leggings with a fitted casual top'),('майк','fitted tank top'),('топ','fitted fashion top')]
    for key,val in clothing_map:
        if key in low: clothing=val
    hairstyle=''
    if any(x in low for x in ('хвост','ponytail')): hairstyle='high ponytail'
    elif any(x in low for x in ('пучок','bun')): hairstyle='neat bun'
    elif any(x in low for x in ('распущ','волнист')): hairstyle='long loose softly wavy hair'
    angle=''
    if any(x in low for x in ('со спины','сзади','back view')): angle='back three-quarter view while keeping her recognizable profile when visible'
    elif any(x in low for x in ('сбоку','профиль','side')): angle='side three-quarter view'
    elif any(x in low for x in ('сверху','верхний ракурс')): angle='slightly high-angle smartphone selfie'
    elif 'полный рост' in low: angle='full-body framing'
    return PhotoRequest(scene=scene,clothing=clothing,hairstyle=hairstyle,angle=angle)

def _reference_path(character:dict,scene:str)->Path:
    identity=character.get('visual_identity',{}); folder=Path(__file__).resolve().parents[1]/identity.get('reference_folder','data/references/anna')
    pref={'selfie':'01_face_front_white_top.png','cafe':'01_face_front_white_top.png','park':'02_full_body_white_top.png','home':'04_lying_hair_down.png','evening':'02_full_body_white_top.png','mirror':'02_full_body_white_top.png','outfit':'02_full_body_white_top.png','fashion':'02_full_body_white_top.png','lingerie':'06_front_black_lingerie.jpg'}
    p=folder/pref.get(scene,'01_face_front_white_top.png')
    if not p.exists():
        refs=[folder/x for x in identity.get('reference_assets',[]) if (folder/x).exists()]
        if not refs: raise FileNotFoundError('У Анны нет доступных reference-фото')
        p=refs[0]
    return p

def _prompt(character:dict,req:PhotoRequest,telegram_id:int)->str:
    state=get_state(telegram_id)
    scene=SCENES.get(req.scene,SCENES['selfie'])
    clothing=req.clothing or state.outfit or ('elegant non-explicit lingerie fashion look with opaque coverage' if req.scene=='lingerie' else 'natural stylish everyday outfit')
    hairstyle=req.hairstyle or state.hairstyle or 'keep the hairstyle from the reference unless the scene naturally requires a small styling adjustment'
    location=req.location or state.location or scene
    angle=req.angle or 'natural flattering camera angle appropriate for the scene'
    return f'''Edit the supplied reference image into a NEW photorealistic photo of the SAME fictional adult woman, {character['name']}, age {character['age']}.
IDENTITY LOCK IS THE TOP PRIORITY. Preserve her recognizable face, eye shape and spacing, nose, lips, jawline, skin tone and stable body proportions. Do not redesign, slim, enlarge, age, de-age or substitute another woman.
Hair: preserve hair color and overall length; requested hairstyle: {hairstyle}.
Clothing: {clothing}.
Location/scene: {location}.
Camera/framing: {angle}.
Mood: {req.mood}.
It should look like an ordinary high-quality smartphone photograph with realistic skin texture, hands and anatomy. Changes to clothing, hairstyle, location, pose and camera angle are allowed; identity and body proportions are not.
Adult character only. No nudity, no transparent explicit exposure, no explicit sexual activity.'''

def _extract(result):
    item=result.data[0]; url=getattr(item,'url',None); raw=getattr(item,'b64_json',None)
    if url: return GeneratedPhoto(url=url)
    if raw: return GeneratedPhoto(data=base64.b64decode(raw))
    raise RuntimeError('Image API returned no image')

async def generate_photo(telegram_id:int,request:PhotoRequest)->GeneratedPhoto:
    character=get_anna(); ref=_reference_path(character,request.scene); prompt=_prompt(character,request,telegram_id)
    with ref.open('rb') as image_file:
        result=await client.images.edit(model=IMAGE_MODEL,image=image_file,prompt=prompt,size=IMAGE_SIZE,quality=IMAGE_QUALITY,n=1)
    return _extract(result)

def _record(telegram_id:int,scene:str,delivery_type:str,file_id=None,url=None):
    uid=ensure_user(telegram_id)
    with SessionLocal() as s:
        usage=s.scalar(select(PhotoDailyUsage).where(PhotoDailyUsage.user_id==uid,PhotoDailyUsage.character_id==CHARACTER_ID,PhotoDailyUsage.usage_date==_today()))
        if not usage:
            usage=PhotoDailyUsage(user_id=uid,character_id=CHARACTER_ID,usage_date=_today()); s.add(usage); s.flush()
        if delivery_type=='free': usage.free_used+=1
        else: usage.paid_used+=1
        s.add(PhotoDelivery(user_id=uid,character_id=CHARACTER_ID,scene=scene,delivery_type=delivery_type,telegram_file_id=file_id,image_url=url)); s.commit()

async def deliver_photo(bot:Bot,chat_id:int,telegram_id:int,request:PhotoRequest,delivery_type:str='free',caption:str|None=None):
    stage=get_relationship_stage(telegram_id)
    if delivery_type=='free' and not scene_allowed_for_stage(request.scene,stage): raise PermissionError('scene_locked')
    if delivery_type=='free' and not has_free_photo(telegram_id): raise PermissionError('quota')
    if delivery_type=='credit' and get_photo_credits(telegram_id)<=0: raise PermissionError('no_credit')
    result=await generate_photo(telegram_id,request); caption=caption or random.choice(AUTO_CAPTIONS.get(request.scene,('вот 😌',)))
    sent=await bot.send_photo(chat_id,result.url,caption=caption) if result.url else await bot.send_photo(chat_id,BufferedInputFile(result.data,filename=f'anna_{request.scene}.png'),caption=caption)
    if delivery_type=='credit':
        consume_photo_credit(telegram_id)
    file_id=sent.photo[-1].file_id if sent.photo else None; _record(telegram_id,request.scene,delivery_type,file_id,result.url)
    update_state(telegram_id,location=request.location or SCENES.get(request.scene),outfit=request.clothing or None,hairstyle=request.hairstyle or None)
    return sent
