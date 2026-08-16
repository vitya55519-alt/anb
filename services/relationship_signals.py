from dataclasses import dataclass
import re

@dataclass(frozen=True)
class SignalDelta:
    relationship: float = 0
    trust: float = 0
    intimacy: float = 0
    event_type: str = "interaction"
    reason: str = "обычное взаимодействие"

CARE = re.compile(r"\b(спасибо|поддерж|понимаю|расскажи|как ты|как у тебя|помнишь|ты говорила|ты рассказывала)\b", re.I)
FLIRT = re.compile(r"\b(красивая|милая|нравишься|люблю тебя|целую|свидани|флирт|сексуаль|возбужд)\b", re.I)
RUDE = re.compile(r"\b(заткнись|дура|идиотка|тупая)\b", re.I)

def infer_delta(text: str) -> SignalDelta:
    if RUDE.search(text):
        return SignalDelta(trust=-2, event_type="negative_interaction", reason="грубая формулировка")
    care = bool(CARE.search(text))
    flirt = bool(FLIRT.search(text))
    if care and flirt:
        return SignalDelta(relationship=2, trust=2, intimacy=1, event_type="warm_flirt", reason="заботливый и флиртующий контекст")
    if care:
        return SignalDelta(relationship=1, trust=2, event_type="care", reason="внимательный или поддерживающий контекст")
    if flirt:
        return SignalDelta(relationship=1, intimacy=1, event_type="flirt", reason="взаимный взрослый флирт")
    return SignalDelta(relationship=0.2, event_type="interaction", reason="обычное общение")
