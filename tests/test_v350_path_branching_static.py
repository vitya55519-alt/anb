"""V3.50.0: the per-character relationship path (romance <-> debauchery).
Quest route answers nudge ``path_axis``; the axis colors the chat tone inside
the stage frame, additionally gates the boldest spicy set, and surfaces on the
character card as a qualitative tenderness<->passion bar (never a raw number).
Static, in the style of the other V3.x pins (the suite cannot import services
without an LLM key, so no behavioral test)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REL_MODELS = (ROOT / 'models' / 'relationship_models.py').read_text(encoding='utf-8')
QUESTS = (ROOT / 'services' / 'quest_service.py').read_text(encoding='utf-8')
ENGINE = (ROOT / 'services' / 'relationship_engine.py').read_text(encoding='utf-8')
SPICY = (ROOT / 'services' / 'spicy_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
WEBAPP_SVC = (ROOT / 'services' / 'webapp_service.py').read_text(encoding='utf-8')
WEBAPP = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_path_axis_column_exists_on_relationship():
    assert 'path_axis: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)' in REL_MODELS


def test_route_inclination_map_and_dilemma_quests():
    assert 'ROUTE_INCLINATION = {' in QUESTS
    # the two new dilemma quests carry clean romance/bold forks
    assert "'late_night_text'" in QUESTS and "'candle_or_adrenaline'" in QUESTS
    assert "('candle_or_adrenaline', 'candles'): 'romance'" in QUESTS
    assert "('candle_or_adrenaline', 'adrenaline'): 'bold'" in QUESTS


def test_complete_route_moves_axis_only_on_canonical_choice():
    assert "def complete_route(telegram_id: int, quest_key: str, route_key: str, paid_replay: bool = False, character_id: str | None = None) -> dict:" in QUESTS
    # the nudge sits inside the ``if first:`` branch, so replays can't farm it
    apply_idx = QUESTS.index("_apply_path(s, uid, char_id, ROUTE_INCLINATION.get((quest_key, route_key), 'neutral'))")
    first_idx = QUESTS.index('first = row.canonical_route is None')
    assert first_idx < apply_idx
    assert 'row.path_axis = max(-100.0, min(100.0,' in QUESTS
    # bot call sites route the axis to the character actually being chatted
    assert 'character_id=get_user_character(cq.from_user.id)' in MAIN
    assert "character_id=get_user_character(message.from_user.id)" in MAIN


def test_chat_tone_injection_is_qualitative_and_stage_bounded():
    assert 'PATH_TONE_THRESHOLD = 40' in ENGINE
    assert "axis = float(getattr(row, 'path_axis', 0.0) or 0.0) if row is not None else 0.0" in ENGINE
    assert 'тяготеет к нежности' in ENGINE
    assert 'тяготеет к страсти' in ENGINE
    # the injected lines are qualitative: the axis variable never interpolates
    # a raw number into the prompt text
    injection = ENGINE.split('def build_relationship_context', 1)[1]
    assert 'Ветвь вашей связи' in injection
    assert '{axis}' not in injection and 'str(axis)' not in injection


def test_boldest_spicy_set_gated_by_path_behind_existing_gates():
    assert 'min_path: int = 0' in SPICY
    assert 'min_path=30' in SPICY
    # pre_checkout keeps level + 18+ and adds the path as an extra AND clause
    assert 'and get_path_axis(ensure_user(query.from_user.id), get_user_character(query.from_user.id)) >= item.min_path' in MAIN
    assert "if item.min_path and get_path_axis(ensure_user(cq.from_user.id), get_user_character(cq.from_user.id)) < item.min_path:" in MAIN


def test_character_card_path_indicator():
    # payload exposes the axis in one batched query (no N+1)
    assert "def _batch_path_axis(telegram_id: int | None, character_ids: list[str]) -> dict[str, float]:" in WEBAPP_SVC
    assert "'path': path_axes.get(card.character_id)" in WEBAPP_SVC
    # the bar renders under the closeness bar, qualitative label only
    assert "id=\"charPathBar\"" in WEBAPP
    assert "ax <= -20 ? L.path_tender : (ax >= 20 ? L.path_free : L.path_balanced)" in WEBAPP
    assert "path_lbl: '💞 Характер связи'" in WEBAPP
    assert "path_end_l: 'Нежность', path_end_r: 'Страсть'" in WEBAPP
