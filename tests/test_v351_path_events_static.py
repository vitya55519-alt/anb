"""V3.51.0: path threshold scenes. Crossing the axis to +/-40 (soft) fires a
text scene, to +/-70 (deep) fires text + a photo, each at most once per
character. The thresholds live in ``relationship_engine`` (PATH_EVENT_SOFT /
PATH_EVENT_DEEP) with a pure ``path_crossings`` helper; ``quest_service``
records a one-shot ``RelationshipMilestone`` keyed ``path_event:{dir}:{depth}``
and only attaches a ``photo_scene`` on the deep tier.

``path_crossings`` is exercised behaviourally by exec-ing just that function +
its two constants out of the source (``ast.get_source_segment``) — no module
import, so the suite still runs without a DB/LLM key."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = (ROOT / 'services' / 'relationship_engine.py').read_text(encoding='utf-8')
QUESTS_SRC = (ROOT / 'services' / 'quest_service.py').read_text(encoding='utf-8')


def _load_crossings():
    tree = ast.parse(ENGINE)
    segs = ['from __future__ import annotations']
    for node in tree.body:
        take = False
        if isinstance(node, ast.Assign):
            take = any(isinstance(t, ast.Name) and t.id in ('PATH_EVENT_SOFT', 'PATH_EVENT_DEEP') for t in node.targets)
        elif isinstance(node, ast.FunctionDef):
            take = node.name == 'path_crossings'
        if take:
            segs.append(ast.get_source_segment(ENGINE, node))
    ns = {}
    exec('\n'.join(s for s in segs if s), ns)
    return ns['path_crossings'], ns['PATH_EVENT_SOFT'], ns['PATH_EVENT_DEEP']


def test_threshold_constants():
    assert 'PATH_EVENT_SOFT = 40' in ENGINE
    assert 'PATH_EVENT_DEEP = 70' in ENGINE


def test_path_crossings_fires_each_threshold_once():
    crossings, soft, deep = _load_crossings()
    assert (soft, deep) == (40, 70)
    assert crossings(0, 45) == [('bold', 'soft')]
    assert crossings(45, 75) == [('bold', 'deep')]
    assert crossings(75, 90) == []          # already past deep
    assert crossings(0, -45) == [('tender', 'soft')]
    assert crossings(-45, -75) == [('tender', 'deep')]
    assert crossings(-75, -80) == []
    assert crossings(-10, 10) == []         # wobble around center fires nothing


def test_fire_path_events_is_one_shot_per_direction_depth():
    assert 'def _fire_path_events(' in QUESTS_SRC
    assert 'key = f\'path_event:{direction}:{depth}\'' in QUESTS_SRC
    # the milestone existence is checked before creating, so it never repeats
    assert 'RelationshipMilestone.milestone_key == key' in QUESTS_SRC
    assert 'if exists:' in QUESTS_SRC
    assert 's.add(RelationshipMilestone(' in QUESTS_SRC


def test_photo_only_on_deep_and_scene_map_present():
    # photo_scene is attached only when depth == 'deep'
    assert "'photo_scene': PATH_EVENT_PHOTO_SCENE.get((direction, depth)) if depth == 'deep' else None" in QUESTS_SRC
    assert "PATH_EVENT_PHOTO_SCENE = {" in QUESTS_SRC
    assert "('tender', 'deep')" in QUESTS_SRC and "('bold', 'deep')" in QUESTS_SRC
