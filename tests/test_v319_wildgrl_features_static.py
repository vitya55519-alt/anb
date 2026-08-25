"""V3.19.0 — WildGrl-style feature pack tests.

Covers: video motion presets, vision reactions to user photos, scenario
hooks, DNA trait bars, the personal character constructor and face-swap
identity anchoring. Static pins + lightweight runtime checks only; no
network calls.
"""
from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
CONSENT = (ROOT / 'services' / 'consent_service.py').read_text(encoding='utf-8')


# ── 1. Video motion presets ────────────────────────────────────────────────

def test_video_presets_defined_with_identity_preserving_prompts():
    cloud_video = importlib.import_module('services.cloud_video_service')
    assert set(cloud_video.VIDEO_PRESETS) == {'kiss', 'hug', 'dance'}
    for key, (label, prompt) in cloud_video.VIDEO_PRESETS.items():
        assert label, f'{key} must have a button label'
        assert 'Preserve her identity' in prompt, f'{key} prompt must lock identity'
        assert 'No wardrobe change' in prompt, f'{key} prompt must lock wardrobe'


def test_video_preset_picker_wired_into_main():
    assert 'VIDEO_PRESETS' in MAIN
    assert '_video_preset_keyboard' in MAIN
    assert 'videopreset:' in MAIN
    # Every animation entry point routes through the preset menu first.
    assert MAIN.count('_show_video_preset_menu(cq.message.chat.id') >= 3
    assert 'motion_preset' in MAIN


def test_video_payload_carries_preset_through_payment():
    assert 'video:<delivery_id>:<preset>' in MAIN
    assert "motion_preset = parts[2] if len(parts) > 2 and parts[2] in VIDEO_PRESETS else None" in MAIN
    assert 'motion_preset=motion_preset' in MAIN


def test_run_video_background_prefers_user_preset():
    assert "preset = VIDEO_PRESETS.get((motion_preset or '').strip())" in MAIN
    assert 'anim_prompt = preset[1]' in MAIN


# ── 2. Vision reactions to user photos ─────────────────────────────────────

def test_photo_reaction_service_runtime_guard():
    reaction_service = importlib.import_module('services.photo_reaction_service')
    assert reaction_service.REACTION_INSTRUCTION
    # Empty payload must short-circuit without touching any provider.
    assert asyncio.run(reaction_service.react_to_photo('')) is None
    assert asyncio.run(reaction_service.react_to_photo('x' * (reaction_service.MAX_BASE64_BYTES + 1))) is None


def test_photo_reaction_wired_into_photo_handler():
    assert 'react_to_photo' in MAIN
    assert '_react_to_user_photo(message)' in MAIN
    assert 'PHOTO_REACTION_ENABLED' in MAIN
    assert 'PHOTO_REACTION_COOLDOWN_SECONDS' in MAIN
    # Sharing a photo grows the bond.
    assert "event_type='meaningful_share'" in MAIN


# ── 3. Scenario hooks ──────────────────────────────────────────────────────

def test_scenario_hooks_defined_for_catalog():
    card_service = importlib.import_module('services.character_card_service')
    for character_id in ('anna_01', 'alena_01', 'maria_01', 'maksim_01', 'leo_01'):
        hook = card_service.get_scenario_hook(character_id)
        assert hook and len(hook) > 40, f'{character_id} needs a cinematic hook'
    assert card_service.get_scenario_hook('no_such_character') is None


def test_scenario_hook_shown_and_sent():
    assert 'get_scenario_hook' in MAIN
    assert "lines.extend(['', f'🎬 {hook}'])" in MAIN
    # Sent as her opening line right after selection.
    assert 'await cq.message.answer(hook)' in MAIN


# ── 4. DNA trait bars ──────────────────────────────────────────────────────

def test_trait_bars_render_most_distinctive_traits():
    dna_service = importlib.import_module('services.character_dna_service')
    bars = dna_service.trait_bars('anna_01')
    assert len(bars) == 4
    for line in bars:
        assert '▓' in line and '░' in line and '/10' in line
    # Most distinctive Anna traits lead: sensuality/teasing/openness rank top.
    joined = '\n'.join(bars)
    assert 'Чувственность' in joined


def test_trait_bars_visible_on_character_card():
    assert 'trait_bars(card.character_id)' in MAIN
    assert "lines.append('Характер:')" in MAIN


# ── 5. Character constructor ───────────────────────────────────────────────

def test_constructor_steps_cover_full_profile():
    ccs = importlib.import_module('services.custom_character_service')
    keys = [step['key'] for step in ccs.CONSTRUCTOR_STEPS]
    assert keys == ['age', 'body', 'hair', 'eyes', 'temperament', 'profession', 'role']
    values = [value for step in ccs.CONSTRUCTOR_STEPS for value, _, _ in step['options']]
    assert len(values) == len(set(values)), 'option callback values must be unique'
    assert set(ccs.OPTION_LABELS) == set(ccs.OPTION_DESCRIPTORS) == set(values)


def test_constructor_character_id_and_detection():
    ccs = importlib.import_module('services.custom_character_service')
    assert ccs.custom_character_id(12345) == 'custom_12345'
    assert ccs.is_custom_character('custom_12345')
    assert not ccs.is_custom_character('anna_01')
    assert not ccs.is_custom_character(None)


def test_constructor_avatar_prompt_builds_from_params():
    ccs = importlib.import_module('services.custom_character_service')
    params = {
        'age': 'age_mid', 'body': 'body_sport', 'hair': 'hair_red',
        'eyes': 'eyes_green', 'temperament': 'temper_bold',
        'profession': 'prof_trainer', 'role': 'role_girlfriend',
        'name': 'Ника',
    }
    prompt = ccs.build_avatar_prompt(params)
    assert 'mid twenties' in prompt and 'red hair' in prompt and 'green eyes' in prompt
    assert 'no nudity' in prompt.lower()
    face_prompt = ccs.build_avatar_prompt(params, face_swap=True)
    assert 'preserve the exact same face' in face_prompt.lower()


def test_constructor_persona_context_replaces_default_role():
    ccs = importlib.import_module('services.custom_character_service')
    persona = ccs.build_persona_context({'role': 'role_secret', 'temperament': 'temper_gentle'}, 'Ника')
    assert 'Ника' in persona
    assert 'secret lover' in persona
    assert 'больше не стандартный персонаж' in persona


def test_constructor_wizard_and_payment_wired():
    assert "'🎨 Мой персонаж'" in MAIN
    assert 'constructor:start' in MAIN and 'constructor:buy' in MAIN
    assert 'cbuild:' in MAIN and 'mychar:chat:' in MAIN
    assert 'CONSTRUCTOR_COST_STARS' in MAIN
    assert "ok = amount == CONSTRUCTOR_COST_STARS" in MAIN
    assert "_finish_constructor(message, charge)" in MAIN
    assert 'generate_custom_avatar' in MAIN


def test_chat_service_injects_custom_persona():
    assert 'custom_persona_context(character_id)' in CHAT
    assert "(persona + '\\n' if persona else '') + behavior" in CHAT


def test_custom_character_model_and_cleanup():
    app_models = importlib.import_module('models.app_models')
    assert app_models.CustomCharacter.__tablename__ == 'custom_characters'
    assert 'CustomCharacter' in CONSENT
    assert 'delete(CustomCharacter)' in CONSENT


# ── 6. Face-swap identity anchor ───────────────────────────────────────────

def test_faceswap_uploads_reference_and_locks_identity():
    photo_service_src = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
    assert 'async def generate_custom_avatar' in photo_service_src
    assert '_seedream_edit(reference_path, prompt' in photo_service_src
    # Wizard offers the face upload step and stores the bytes for generation.
    assert 'cbuild:face_upload' in MAIN
    assert "cons['face_bytes'] = face_bytes" in MAIN
    assert 'face_swap=bool(face_path)' in MAIN


# ── 7. V3.19.1: admin free constructor + video diagnostics ────────────────

def test_admin_free_constructor():
    assert 'async def _finish_constructor(message: types.Message, charge: str | None):' in MAIN
    assert "'✅ Создать · бесплатно (админ)'" in MAIN
    # Admins skip the invoice and run generation with no charge.
    assert '_finish_constructor(cq.message, None)' in MAIN
    # Refund logic only fires for paid runs.
    assert 'if charge:' in MAIN[MAIN.index('constructor avatar generation failed'):]


def test_video_unavailable_diagnostics_for_admins():
    assert 'def _video_unavailable_text(' in MAIN
    assert 'Проверь переменные окружения на Railway' in MAIN
    assert 'GEMINI_API_KEY' in MAIN and 'REPLICATE_API_TOKEN' in MAIN
    # All animation entry points use the diagnostic alert.
    assert MAIN.count('_video_unavailable_text(cq.from_user.id)') >= 3
