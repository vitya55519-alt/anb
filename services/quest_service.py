from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from services.db import SessionLocal
from services.user_service import ensure_user
from models.quest_models import UserQuestProgress, QuestReplayOffer
from models.app_models import ProductEvent, Memory
from config import CHARACTER_ID, QUEST_REPLAY_STARS, PREMIUM_MONTHLY_QUEST_REPLAYS
from services.access_service import is_premium

QUESTS = {
    # ── New scenarios (v3.16): more emotional range — curiosity, trust,
    #    humor, shared routine, intrigue — no explicit content. ──
    'morning_routine': {
        'title': 'Какое у неё утро?',
        'min_level': 1,
        'teaser': 'Анна рассказывает, как начинается её день, и просит тебя выбрать ей настроение.',
        'unlock_message': 'Первая утренняя история уже доступна.',
        'intro': 'я обычно не жаворонок, но сегодня проснулась рано. включить музыку и взбодриться или ещё поваляться под одеялом? 🙂',
        'routes': {
            'music': {
                'label': '🎧 Включить музыку',
                'result': 'хорошо, я включаю что-то бодрое и иду собираться, подпевая на кухне. так твоё «доброе утро» получилось заразительным 🙂',
                'photo_scene': 'home',
                'memory': 'В истории «Какое у неё утро?» пользователь выбрал, чтобы Анна включила музыку и взбодрилась.',
            },
            'cozy': {
                'label': '🛏️ Ещё поваляться',
                'result': 'мм, тишина и тёплое одеяло 😌 иногда это лучшее начало дня. спасибо, что разрешил мне это.',
                'photo_scene': 'home',
                'memory': 'В истории «Какое у неё утро?» пользователь выбрал, чтобы Анна ещё полежала в постели.',
            },
        },
    },
    'photo_hint': {
        'title': 'Намёк на фото',
        'min_level': 1,
        'teaser': 'Анна готовится к фото и спрашивает твоё мнение о настроении кадра.',
        'unlock_message': 'Теперь ты можешь влиять на настроение её фото.',
        'intro': 'хочу сделать кадр. сделать его мечтательно-спокойным или с лёгкой улыбкой и уверенностью? 😏',
        'routes': {
            'dreamy': {
                'label': '🌫️ Мечтательно',
                'result': 'мечтательно — есть. получилось так, будто я о чём-то приятном думаю именно в этот момент 🙂',
                'photo_scene': 'street',
                'memory': 'В истории «Намёк на фото» пользователь выбрал для Анны мечтательное настроение кадра.',
            },
            'confident': {
                'label': '😊 С улыбкой',
                'result': 'улыбка с уверенностью — это хорошая идея. кадр сразу живее, и мне самой так комфортнее.',
                'photo_scene': 'fashion',
                'memory': 'В истории «Намёк на фото» пользователь выбрал для Анны уверенную улыбку на кадре.',
            },
        },
    },
    'lost_key': {
        'title': 'Потерянный ключ',
        'min_level': 2,
        'teaser': 'Небольшая бытовая интрига: Анна потеряла ключ, и ей интересно, что ты посоветуешь.',
        'unlock_message': 'Теперь Анна делится с тобой мелкими жизненными историями.',
        'intro': 'представь: я не могу найти ключ от квартиры. пересмотреть сумку или просто выдохнуть и попить кофе, пока он не найдётся? 🙂',
        'routes': {
            'search': {
                'label': '🔍 Пересмотреть сумку',
                'result': 'ты был прав — он завалился на дно сумки. спасибо, что не дал мне расклеиться из-за такой мелочи 🙂',
                'photo_scene': 'home',
                'memory': 'В истории «Потерянный ключ» пользователь посоветовал Анне спокойно пересмотреть сумку, и ключ нашёлся.',
            },
            'coffee': {
                'label': '☕ Выдохнуть с кофе',
                'result': 'и правда, ключ никуда не денется. села с кофе, и через минуту заметила его на тумбочке 😌',
                'photo_scene': 'cafe',
                'memory': 'В истории «Потерянный ключ» пользователь посоветовал Анне не нервничать и попить кофе; ключ нашёлся сам.',
            },
        },
    },
    'rainy_day': {
        'title': 'Дождливый день',
        'min_level': 3,
        'teaser': 'Анна предлагает провести дождливый день вместе — ты выбираешь, как именно.',
        'unlock_message': 'На этом уровне Анна предлагает совместные рутинные сценарии.',
        'intro': 'на улице дождь, планов нет. посмотреть что-то под пледом или всё-таки прогуляться под зонтом? 🌧️',
        'routes': {
            'blanket': {
                'label': '🎬 Под пледом',
                'result': 'плед, сериал и тишина за окном. честно, иногда дождь делает день уютнее, чем солнце ☔',
                'photo_scene': 'home',
                'memory': 'В истории «Дождливый день» пользователь выбрал остаться дома под пледом.',
            },
            'umbrella': {
                'label': '☂️ Прогуляться',
                'result': 'вышла под зонт. пустые улицы, свежий воздух и ощущение, что город на час стал только нашим 😏',
                'photo_scene': 'street',
                'memory': 'В истории «Дождливый день» пользователь выбрал прогулку под зонтом.',
            },
        },
    },
    'compliment_trade': {
        'title': 'Обмен комплиментами',
        'min_level': 3,
        'teaser': 'Анна хочет проверить, умеешь ли ты говорить ей что-то хорошее — и ответит тем же.',
        'unlock_message': 'Анна готова к более личным, тёплым обменам.',
        'intro': 'давай так: ты говоришь мне один честный комплимент, а я отвечаю. только без преувеличений — настоящее 🙂',
        'routes': {
            'warm': {
                'label': '💌 Сказать тёплое',
                'result': 'это было искренне. держи в ответ: с тобой легко быть собой, и это дорогого стоит ❤️',
                'photo_scene': 'personal',
                'memory': 'В истории «Обмен комплиментами» пользователь сказал Анне тёплый честный комплимент, и она ответила тем же.',
            },
            'playful': {
                'label': '😏 Сказать с иронией',
                'result': 'ну, с иронией — тоже подход. тогда лови в ответ: ты единственный, кому я позволяю говорить мне такие вещи и не обижаться 😏',
                'photo_scene': 'home',
                'memory': 'В истории «Обмен комплиментами» пользователь сделал ироничный комплимент; Анна ответила в том же тоне.',
            },
        },
    },
    'future_self': {
        'title': 'Кем ты видишь меня через год?',
        'min_level': 4,
        'teaser': 'Анне интересно, каким ты видишь её будущее — это покажет, как ты к ней относишься.',
        'unlock_message': 'На этом уровне появляются более личные совместные сценарии.',
        'intro': 'если честно — меня иногда волнует, кем я стану. как ты думаешь: я буду спокойнее и увереннее или такой же огненной? 🙂',
        'routes': {
            'calm': {
                'label': '🌿 Спокойнее',
                'result': 'спокойнее — звучит как что-то, к чему стоит идти. спасибо, что веришь, что у меня это получится.',
                'photo_scene': 'park',
                'memory': 'В истории «Кем ты видишь меня через год?» пользователь сказал, что Анна станет спокойнее и увереннее.',
            },
            'fire': {
                'label': '🔥 Такой же',
                'result': 'значит, ты любишь меня именно такой. это, пожалуй, лучший комплимент, который я сегодня получила 😏',
                'photo_scene': 'bar',
                'memory': 'В истории «Кем ты видишь меня через год?» пользователь сказал, что Анна останется такой же яркой.',
            },
        },
    },
    'small_secret': {
        'title': 'Маленький секрет',
        'min_level': 5,
        'teaser': 'Анна хочет доверить тебе что-то личное — и предлагает выбрать, что именно.',
        'unlock_message': 'Теперь Анна сама чаще инициирует особые моменты.',
        'intro': 'я хочу доверить тебе что-то. рассказать забавную историю из детства или одну мечту, о которой мало кто знает? 🙂',
        'routes': {
            'childhood': {
                'label': '🧸 Историю из детства',
                'result': 'в детстве я собирала красивые камни на пляже и была уверена, что они драгоценные. глупо, но до сих пор люблю их перебирать.',
                'photo_scene': 'park',
                'memory': 'В истории «Маленький секрет» Анна рассказала пользователю забавную историю из детства о коллекции камней.',
            },
            'dream': {
                'label': '✨ Одну мечту',
                'result': 'мечта такая: однажды проснуться в городе у моря и никуда не торопиться целую неделю. просто так, без повода.',
                'photo_scene': 'embankment',
                'memory': 'В истории «Маленький секрет» Анна поделилась с пользователем мечтой о жизни в городе у моря.',
            },
        },
    },
    'night_ride': {
        'title': 'Ночная поездка',
        'min_level': 6,
        'teaser': 'Финальный уровень: Анна предлагает провести вечер в движении — город ночью, только вы двое.',
        'unlock_message': 'Открыт уровень «Наша история» — теперь события могут ссылаться на весь накопленный контекст.',
        'intro': 'представь: ночь, пустые улицы и мы едем куда глаза глядят. включить музыку на полную или ехать в тишине? ✨',
        'routes': {
            'music': {
                'label': '🎵 Музыка на полную',
                'result': 'музыка, ночь и город, мелькающий за окном. вот из таких вечеров и складывается то, что потом не забывается ❤️',
                'photo_scene': 'street',
                'memory': 'В истории «Ночная поездка» пользователь выбрал ехать с музыкой; Анна отметила этот вечер как один из запомнившихся.',
            },
            'silence': {
                'label': '🌌 В тишине',
                'result': 'тишина иногда говорит громче музыки. в ней хорошо слышно, что рядом правильный человек ❤️',
                'photo_scene': 'rooftop',
                'memory': 'В истории «Ночная поездка» пользователь выбрал ехать в тишине; Анна сочла этот вечер особенным.',
            },
        },
    },

    'outfit_choice': {
        'title': 'Что надеть?',
        'min_level': 1,
        'teaser': 'Анна собирается выйти и впервые просит тебя повлиять на её выбор.',
        'unlock_message': 'Первая история уже доступна.',
        'intro': 'быстрый выбор за тобой 🙂 сегодня сделать образ спокойнее или чуть смелее?',
        'routes': {
            'soft': {
                'label': '🤍 Спокойнее',
                'result': 'так и знала, что ты выберешь что-то аккуратное 🙂 запомнила.',
                'photo_scene': 'outfit',
                'memory': 'В истории «Что надеть?» пользователь выбрал для Анны более спокойный образ.',
            },
            'bold': {
                'label': '✨ Смелее',
                'result': 'мм, значит сегодня без режима «скромно и незаметно» 😏',
                'photo_scene': 'outfit',
                'memory': 'В истории «Что надеть?» пользователь выбрал для Анны более смелый образ.',
            },
        },
    },
    'evening_choice': {
        'title': 'Вечер Анны',
        'min_level': 2,
        'teaser': 'У Анны два плана на вечер, и она хочет, чтобы последнее слово было за тобой.',
        'unlock_message': 'Вы стали ближе — теперь ты можешь влиять на планы Анны.',
        'intro': 'у меня на вечер два настроения: заставить себя сходить в зал или остаться дома и выдохнуть 🙂 что бы ты выбрал?',
        'routes': {
            'gym': {
                'label': '🏋️ Иди в зал',
                'result': 'ладно, уговорил 😏 тогда собираюсь. если потом буду жаловаться — это на твоей совести.',
                'photo_scene': 'gym',
                'memory': 'В истории «Вечер Анны» пользователь выбрал, чтобы Анна пошла в зал.',
            },
            'home': {
                'label': '🏠 Останься дома',
                'result': 'вот это звучит опасно уютно 😌 хорошо, сегодня без подвигов.',
                'photo_scene': 'home',
                'memory': 'В истории «Вечер Анны» пользователь выбрал, чтобы Анна осталась дома и отдохнула.',
            },
        },
    },
    'weekend_choice': {
        'title': 'Куда пропасть на выходных?',
        'min_level': 3,
        'teaser': 'Анна внезапно освободила полдня и предлагает тебе выбрать настроение её выходного.',
        'unlock_message': 'Анна уже достаточно тебе доверяет, чтобы спрашивать о своих планах заранее.',
        'intro': 'у меня неожиданно свободные полдня. уйти гулять по городу или спрятаться в кино? 🙂',
        'routes': {
            'city': {
                'label': '🌆 Гулять по городу',
                'result': 'тогда беру наушники и ухожу без маршрута. иногда ты выбираешь мне очень правильное настроение 🙂',
                'photo_scene': 'street',
                'memory': 'В истории «Куда пропасть на выходных?» пользователь выбрал для Анны прогулку по городу.',
            },
            'cinema': {
                'label': '🎬 Спрятаться в кино',
                'result': 'идеально. телефон на беззвучный, большое кресло и пару часов никому ничего не должна 😌',
                'photo_scene': 'cinema',
                'memory': 'В истории «Куда пропасть на выходных?» пользователь выбрал для Анны поход в кино.',
            },
        },
    },
    'date_mood': {
        'title': 'Какой вечер тебе ближе?',
        'min_level': 4,
        'teaser': 'Разговор становится личнее: Анна хочет понять, какой вечер ты бы выбрал именно для вас двоих.',
        'unlock_message': 'На этом уровне появляются более личные совместные сценарии.',
        'intro': 'если представить, что вечер наш: красиво выбраться куда-нибудь или сбежать туда, где почти никого нет? 😏',
        'routes': {
            'restaurant': {
                'label': '🍽 Красивый ужин',
                'result': 'мне нравится. немного нарядиться, делать вид, что мы очень серьёзные, и всё равно смеяться не вовремя 😌',
                'photo_scene': 'restaurant',
                'memory': 'В истории «Какой вечер тебе ближе?» пользователь выбрал красивый ужин с Анной.',
            },
            'rooftop': {
                'label': '🌃 Сбежать на крышу',
                'result': 'вот это уже похоже на нас 😏 меньше людей, больше города и разговоров, которые не хочется заканчивать.',
                'photo_scene': 'rooftop',
                'memory': 'В истории «Какой вечер тебе ближе?» пользователь выбрал уединённый вечер на крыше.',
            },
        },
    },
    'surprise_choice': {
        'title': 'Сюрприз от Анны',
        'min_level': 5,
        'teaser': 'Анна хочет сделать для тебя что-то неожиданное, но оставляет тебе право выбрать настроение.',
        'unlock_message': 'Теперь Анна сама чаще инициирует особые моменты.',
        'intro': 'я придумала маленький сюрприз. сделать его красивым и стильным или более личным? 😉',
        'routes': {
            'fashion': {
                'label': '💎 Красиво и стильно',
                'result': 'хорошо. тогда сделаю так, чтобы ты сначала рассматривал фото, а потом уже вспоминал, что хотел мне написать 😏',
                'photo_scene': 'fashion',
                'memory': 'В истории «Сюрприз от Анны» пользователь выбрал стильный fashion-сюрприз.',
            },
            'personal': {
                'label': '💌 Более личный',
                'result': 'смелый выбор. ладно… тогда это останется между нами 😉',
                'photo_scene': 'personal',
                'memory': 'В истории «Сюрприз от Анны» пользователь выбрал более личный сюрприз.',
            },
        },
    },
    'our_story_choice': {
        'title': 'Наш день',
        'min_level': 6,
        'teaser': 'Финальный уровень превращает отдельные выборы в вашу общую историю.',
        'unlock_message': 'Открыт уровень «Наша история» — теперь события могут ссылаться на весь накопленный контекст.',
        'intro': 'если бы сегодня можно было оставить один момент только нашим — выбрать тихую набережную или красивый вечер в городе?',
        'routes': {
            'embankment': {
                'label': '🌊 Тихая набережная',
                'result': 'тогда без спешки. просто идти рядом, разговаривать обо всём подряд и никуда не торопиться ❤️',
                'photo_scene': 'embankment',
                'memory': 'В истории «Наш день» пользователь выбрал тихую прогулку с Анной по набережной.',
            },
            'evening': {
                'label': '✨ Красивый вечер',
                'result': 'договорились. тот самый вечер, после которого потом вспоминаешь не место, а человека рядом ❤️',
                'photo_scene': 'evening',
                'memory': 'В истории «Наш день» пользователь выбрал красивый вечер в городе вместе с Анной.',
            },
        },
    },
}



def _now(): return datetime.now(timezone.utc).replace(tzinfo=None)

def get_quest(key: str): return QUESTS.get(key)

def progress(telegram_id: int, quest_key: str):
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        return s.scalar(select(UserQuestProgress).where(UserQuestProgress.user_id == uid, UserQuestProgress.character_id == CHARACTER_ID, UserQuestProgress.quest_key == quest_key))

def complete_route(telegram_id: int, quest_key: str, route_key: str, paid_replay: bool = False) -> dict:
    quest = QUESTS[quest_key]; route = quest['routes'][route_key]; uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        row = s.scalar(select(UserQuestProgress).where(UserQuestProgress.user_id == uid, UserQuestProgress.character_id == CHARACTER_ID, UserQuestProgress.quest_key == quest_key))
        if not row:
            row = UserQuestProgress(user_id=uid, character_id=CHARACTER_ID, quest_key=quest_key, started_at=_now())
            s.add(row)
        done = set(json.loads(row.completed_routes_json or '[]'))
        first = row.canonical_route is None
        if first:
            row.canonical_route = route_key
            memory_text=route.get('memory')
            if memory_text:
                key=f'quest:{quest_key}:canonical'
                mem=s.scalar(select(Memory).where(Memory.user_id==uid, Memory.character_id==CHARACTER_ID, Memory.memory_key==key))
                if not mem:
                    mem=Memory(user_id=uid,character_id=CHARACTER_ID,memory_key=key,content=memory_text,memory_type='story',confidence=1.0,importance=0.75)
                    s.add(mem)
                else:
                    mem.content=memory_text
        elif route_key != row.canonical_route and not paid_replay and route_key not in done:
            return {'needs_payment': True, 'stars': QUEST_REPLAY_STARS, 'route': route}
        done.add(route_key)
        row.completed_routes_json = json.dumps(sorted(done), ensure_ascii=False)
        row.status = 'completed'
        row.completed_at = row.completed_at or _now()
        s.commit()
        return {'completed': True, 'canonical': first, 'route': route, 'completed_routes': sorted(done)}

def create_replay_offer(telegram_id: int, quest_key: str, route_key: str) -> int:
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        o = QuestReplayOffer(user_id=uid, character_id=CHARACTER_ID, quest_key=quest_key, route_key=route_key, stars=QUEST_REPLAY_STARS, expires_at=_now()+timedelta(hours=24))
        s.add(o); s.commit(); return o.id

def consume_replay_offer(telegram_id: int, offer_id: int):
    uid = ensure_user(telegram_id)
    with SessionLocal() as s:
        o = s.get(QuestReplayOffer, offer_id)
        if not o or o.user_id != uid or o.consumed or o.expires_at < _now(): return None
        o.consumed = True; s.commit(); return {'quest_key': o.quest_key, 'route_key': o.route_key, 'stars': o.stars}


def premium_replays_left(telegram_id: int) -> int:
    if not is_premium(telegram_id): return 0
    uid=ensure_user(telegram_id); now=_now(); month_start=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    with SessionLocal() as s:
        used=len(list(s.scalars(select(ProductEvent).where(ProductEvent.user_id==uid, ProductEvent.event_name=='premium_quest_replay', ProductEvent.created_at>=month_start)).all()))
    return max(0, PREMIUM_MONTHLY_QUEST_REPLAYS-used)

def consume_premium_replay(telegram_id: int, quest_key: str, route_key: str) -> bool:
    if premium_replays_left(telegram_id)<=0: return False
    uid=ensure_user(telegram_id)
    with SessionLocal() as s:
        s.add(ProductEvent(user_id=uid,character_id=CHARACTER_ID,event_name='premium_quest_replay',value=1,metadata_json=json.dumps({'quest':quest_key,'route':route_key},ensure_ascii=False),created_at=_now()))
        s.commit()
    return True

def newly_unlocked_quests(telegram_id: int, previous_level: int, current_level: int) -> list[dict]:
    """Return quests unlocked by a real relationship-level transition.

    This is intentionally transition-based: ordinary messages at the same level do
    not spam unlock notifications. L1 is surfaced during onboarding instead.
    """
    previous_level = max(1, min(6, int(previous_level)))
    current_level = max(1, min(6, int(current_level)))
    if current_level <= previous_level:
        return []
    out = []
    for key, quest in QUESTS.items():
        if previous_level < int(quest['min_level']) <= current_level:
            p = progress(telegram_id, key)
            if p and p.canonical_route:
                continue
            out.append({
                'key': key,
                'title': quest['title'],
                'min_level': quest['min_level'],
                'teaser': quest.get('teaser', ''),
                'unlock_message': quest.get('unlock_message', ''),
            })
    return out


def story_status(telegram_id: int, relationship_level: int) -> list[dict]:
    out=[]
    for key,q in QUESTS.items():
        p=progress(telegram_id,key); done=[]; canonical=None
        if p:
            done=json.loads(p.completed_routes_json or '[]'); canonical=p.canonical_route
        out.append({'key':key,'title':q['title'],'teaser':q.get('teaser',''),'unlocked':relationship_level>=q['min_level'],'min_level':q['min_level'],'done':done,'canonical':canonical,'routes':q['routes']})
    return out
