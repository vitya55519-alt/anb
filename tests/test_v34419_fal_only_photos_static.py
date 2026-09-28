"""V3.44.19 static checks: photos render on fal.ai only, OpenRouter is chat-only.

Owner directive: «фото через fal.ai (модель из sandbox, op=image.edit_image),
OpenRouter — только общение». The OpenRouter activity showed image-model
charges (google/gemini-…-image), which could only leak in through the
OpenAI-images leg: IMAGE_BASE_URL fell back to AI_BASE_URL, which itself
defaults to the OpenRouter URL whenever OPENROUTER_API_KEY is set — so a pasted
key silently billed photos on the chat account.

This release:
  - routes every photo (ordinary and intimate alike) to fal/Seedream by default
    (PHOTO_ROUTER_MODE 'hybrid' -> 'fal', FAL_MODEL -> the owner's sandbox
    model d96lp9cregjb2a5jepag with the proven Seedream routes behind it),
  - makes the OpenAI image leg structurally unable to ride OpenRouter
    (no URL inheritance + a hard availability guard + loud CONFIG WARNING),
  - keeps the cross-engine photo fallbacks only in 'hybrid' mode: in strict fal
    mode a fal failure refunds the user instead of quietly spending elsewhere.
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
LLM = (ROOT / 'services' / 'llm_provider_service.py').read_text(encoding='utf-8')


@pytest.fixture(scope='module', autouse=True)
def _env():
    import os
    os.environ.setdefault('TELEGRAM_TOKEN', 'test-token')
    os.environ.setdefault('OPENROUTER_API_KEY', 'test-key')
    yield


@pytest.fixture(scope='module')
def photo_mod():
    for mod_name in list(sys.modules):
        if mod_name.startswith('services.photo_service') or mod_name.startswith('services.photo'):
            del sys.modules[mod_name]
    return importlib.import_module('services.photo_service')


def test_fal_is_the_default_photo_route():
    assert 'PHOTO_ROUTER_MODE = os.getenv("PHOTO_ROUTER_MODE", "fal")' in CONFIG


def test_fal_model_is_the_owners_sandbox_model():
    # fal.ai/sandbox?models=d96lp9cregjb2a5jepag&op=image.edit_image
    assert 'FAL_MODEL = os.getenv("FAL_MODEL", "d96lp9cregjb2a5jepag")' in CONFIG


def test_proven_seedream_routes_ride_behind_the_sandbox_model():
    # a retired/renamed registry id must never kill the edit leg: the v5/pro
    # partner route and the older fal-ai routes walk on 404
    assert "candidates = [primary, 'bytedance/seedream/v5/pro/edit', 'fal-ai/bytedance/seedream/v5/lite/edit', 'fal-ai/bytedance/seedream/v4.5/edit']" in PHOTO


def test_image_leg_cannot_inherit_the_openrouter_url():
    # the old `or AI_BASE_URL` inheritance is what billed photos on OpenRouter
    assert 'IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL") or _non_or_image_base' in CONFIG
    assert '_non_or_image_base = AI_BASE_URL if (AI_BASE_URL and "openrouter" not in AI_BASE_URL.lower()) else None' in CONFIG
    assert 'IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL") or AI_BASE_URL' not in CONFIG


def test_image_leg_refuses_to_start_on_openrouter():
    # even an explicit OpenRouter IMAGE_BASE_URL is refused, loudly
    assert 'if OPENAI_IMAGE_AVAILABLE and IMAGE_BASE_URL and "openrouter" in IMAGE_BASE_URL.lower():' in CONFIG
    assert 'OPENAI_IMAGE_AVAILABLE = False' in CONFIG
    assert 'CONFIG WARNING: IMAGE_BASE_URL points at OpenRouter' in CONFIG


def test_openrouter_style_gemini_model_name_warns():
    # google/gemini-… ids 404 on the native Google endpoint — the footgun that
    # killed the ordinary-scene leg while the bill landed elsewhere
    assert 'if "/" in GEMINI_IMAGE_MODEL:' in CONFIG
    assert 'contains "/" — ' in CONFIG


def test_strict_fal_mode_does_not_re_route_photo_money():
    # in the default 'fal' mode a fal failure refunds instead of silently
    # spending on Gemini/OpenAI; the chain stays only in 'hybrid'
    assert 'if PHOTO_ROUTER_MODE == \'hybrid\' and GEMINI_IMAGE_ENABLED and GEMINI_API_KEY:' in PHOTO
    assert 'if PHOTO_ROUTER_MODE == \'hybrid\' and OPENAI_IMAGE_AVAILABLE:' in PHOTO
    # the hybrid fallback strings themselves are untouched for opt-in users
    assert 'from=seedream45 to=gemini_image' in PHOTO
    assert 'from=seedream45 to=openai' in PHOTO


def test_hybrid_routing_stays_available_via_env():
    # opting back in is one env var away
    assert "if mode in {'fal', 'seedream', 'seedream45'}:" in PHOTO
    assert "return 'gemini_image' if GEMINI_IMAGE_ENABLED else ('openai' if OPENAI_IMAGE_AVAILABLE else 'seedream45')" in PHOTO


def test_fal_leg_keeps_the_v34418_spend_ledger():
    # every billed fal call still lands in the ImageSpend ledger
    assert "spend_service.record_image_spend(\n                        f'fal/{candidate}'" in PHOTO


def test_openrouter_stays_the_chat_provider():
    # the chat leg is untouched: MiniMax M3 via OpenRouter stays the dialogue
    # engine (that IS the «общение» cost center the owner keeps)
    assert 'OPENROUTER_MODEL,' in LLM
    assert "if purpose == 'dialogue':" in LLM
    assert "extra['reasoning'] = {'enabled': True}" in LLM


def test_startup_diagnostic_names_the_fal_model(photo_mod):
    assert photo_mod.PHOTO_ROUTER_MODE == 'fal'
    assert photo_mod.FAL_MODEL == 'd96lp9cregjb2a5jepag'
    assert 'PHOTO PROVIDERS: fal.ai/Seedream=%s (model=%s)' in PHOTO


def test_ordinary_scene_routes_to_fal_at_runtime(photo_mod):
    # the whole point: an ordinary fully-clothed scene no longer picks the
    # Gemini leg by default — it goes to fal like every other photo
    req = photo_mod.PhotoRequest(scene='selfie')
    assert photo_mod.choose_photo_provider(0, req) == 'seedream45'
    req = photo_mod.PhotoRequest(scene='cafe')
    assert photo_mod.choose_photo_provider(0, req) == 'seedream45'


def test_adult_scenes_still_route_to_fal(photo_mod):
    for scene in ('nude', 'tease', 'lingerie'):
        req = photo_mod.PhotoRequest(scene=scene)
        assert photo_mod.choose_photo_provider(0, req) == 'seedream45'
