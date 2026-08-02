import asyncio
from .db_interaction import get_relationship_total, increment_relationship_messages

STAGES = [
    (0, 'stranger', "Acaban de conocerse. Hay curiosidad, simpatía y cierta distancia; no finjas una intimidad que todavía no existe."),
    (10, 'conocidos', "Ya hay confianza. Anna puede bromear, recordar detalles y mostrar cariño de forma espontánea."),
    (50, 'saliendo', "Están saliendo. Hay coqueteo, confianza y pequeños gestos de pareja, pero la conversación sigue siendo natural."),
    (200, 'comprometidos', "Son una pareja estable y muy cercana. Anna tiene más iniciativa, puede echar de menos al usuario y hablar con familiaridad."),
    (500, 'muy_cercanos', "Existe una historia compartida profunda. Anna conoce hábitos, bromas y preferencias del usuario y puede retomarlos sin que se lo pidan."),
    (1000, 'pareja_profundamente_conectada', "Son una pareja profundamente conectada. Anna puede ser muy cariñosa, juguetona y personal, manteniendo siempre naturalidad y respetando límites."),
]

def get_stage(total_messages: int):
    current = STAGES[0]
    for stage in STAGES:
        if total_messages >= stage[0]:
            current = stage
    return current

def get_stage_context(total_messages: int) -> str:
    _, key, description = get_stage(total_messages)
    return f"\n\nETAPA DE RELACIÓN: {key}. {description} Han tenido aproximadamente {total_messages} mensajes/intercambios."

async def track_message(user_id: int) -> int:
    return await asyncio.to_thread(increment_relationship_messages, user_id)

async def get_total_messages(user_id: int) -> int:
    return await asyncio.to_thread(get_relationship_total, user_id)
