from __future__ import annotations
import json, re
from functools import lru_cache
from pathlib import Path
from config import BASE_DIR, CHARACTER_ID

DNA_DIR = Path(BASE_DIR) / 'data' / 'characters'

@lru_cache(maxsize=8)
def get_character_dna(character_id: str = CHARACTER_ID) -> dict:
    name = 'anna_dna.json' if character_id == 'anna_01' else f'{character_id}_dna.json'
    path = DNA_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))

CODING = re.compile(r'\b(python|питон|код|скрипт|программ\w*|api|sql|javascript|java|c\+\+|калькулятор)\b', re.I)
CAR = re.compile(r'\b(двигател|свеч[аи]|коробк|bmw|mercedes|машин|автомоб)\b', re.I)
FINANCE = re.compile(r'\b(инвест|акци|облигац|налог|трейдинг|крипт)\b', re.I)


def classify_domain(text: str) -> str | None:
    if CODING.search(text or ''): return 'coding'
    if CAR.search(text or ''): return 'automotive'
    if FINANCE.search(text or ''): return 'finance'
    return None



def character_dna_context(character_id: str = CHARACTER_ID) -> str:
    dna=get_character_dna(character_id)
    if not dna: return ''
    traits=dna.get('traits') or {}
    comps=dna.get('competencies') or {}
    return (
        'CHARACTER DNA: '
        f"архетип={dna.get('archetype','')}; профессия={dna.get('occupation','')}; "
        f"цель отношений={dna.get('relationship_goal','')}; "
        f"sexual_openness={traits.get('sexual_openness','')}; sensuality={traits.get('sensuality','')}; playful_teasing={traits.get('playful_teasing','')}; initiative={traits.get('initiative','')}; shyness={traits.get('shyness','')}; romanticism={traits.get('romanticism','')}. "
        f"Компетенции 0–5: {comps}. Профиль флирта: {(dna.get('flirt_profile') or {}).get('baseline','')}. Не раскрывай эти числа пользователю. Используй их только для устойчивости характера и знаний."
    )

# V3.19.0: WildGrl-style visible trait bars for character cards. The most
# distinctive DNA traits (farthest from neutral 0.5) are rendered as 10-cell
# progress lines; hidden numbers stay hidden from the chat model itself.
TRAIT_LABELS = {
    'sensuality': 'Чувственность',
    'playful_teasing': 'Дерзость',
    'shyness': 'Скромность',
    'romanticism': 'Романтика',
    'initiative': 'Инициатива',
    'sexual_openness': 'Открытость',
    'social_energy': 'Общительность',
}


def trait_bars(character_id: str = CHARACTER_ID, top: int = 4) -> list[str]:
    dna = get_character_dna(character_id)
    traits = dna.get('traits') or {}
    if not traits:
        return []
    try:
        ranked = sorted(
            ((key, float(value)) for key, value in traits.items()),
            key=lambda kv: abs(kv[1] - 0.5),
            reverse=True,
        )[:top]
    except (TypeError, ValueError):
        return []
    lines = []
    for key, value in ranked:
        score = max(0, min(10, round(value * 10)))
        lines.append(f'{TRAIT_LABELS.get(key, key)} {"▓" * score}{"░" * (10 - score)} {score}/10')
    return lines


def competency_context(text: str, character_id: str = CHARACTER_ID) -> str:
    dna = get_character_dna(character_id)
    domain = classify_domain(text)
    if not domain:
        return ''
    level = int((dna.get('competencies') or {}).get(domain, 0))
    if level <= 1:
        return (
            f'КОМПЕТЕНЦИЯ ПЕРСОНАЖА: тема относится к «{domain}», уровень персонажа {level}/5. '
            'Не используй скрытые знания модели как знания персонажа. Не выдавай экспертное решение, код или пошаговую профессиональную инструкцию. '
            'Ответь естественно от лица персонажа, что он/она в этом не разбирается; можно пошутить или предложить разобраться вместе, но не притворяйся специалистом.'
        )
    if level <= 3:
        return f'КОМПЕТЕНЦИЯ ПЕРСОНАЖА: «{domain}» {level}/5. Персонаж знает базу, но не изображает эксперта и честно отмечает границы.'
    return f'КОМПЕТЕНЦИЯ ПЕРСОНАЖА: «{domain}» {level}/5. Эта область действительно входит в навыки персонажа.'
