"""V3.44.18 static checks: money telemetry + daily brakes.

Owner alarm: $14 burned in five days while the free tier is capped at 20
messages/day/person, and /stats could not name a single cent. Three accounting
blind spots made that structural (see spend_service docstring):
  1. generate_text threw the provider ``usage`` block away,
  2. photo cost was recorded only for DELIVERED images (49% of renders failed
     invisibly),
  3. GEMINI_IMAGE_ESTIMATED_COST_USD — the MAIN photo engine — defaulted to 0,
     so «себестоимость фото: $0.00» was an artifact, not truth.

This release adds two ledgers (LlmUsage / ImageSpend), records every billed
call, prices the ones the provider does not report, renders a 💸 block in
/stats, and installs two daily brakes (aux LLM + image generation) that never
touch the reply the user reads. These tests pin the wiring statically.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / 'config.py').read_text(encoding='utf-8')
MODELS = (ROOT / 'models' / 'app_models.py').read_text(encoding='utf-8')
SPEND = (ROOT / 'services' / 'spend_service.py').read_text(encoding='utf-8')
LLM = (ROOT / 'services' / 'llm_provider_service.py').read_text(encoding='utf-8')
CHAT = (ROOT / 'services' / 'chat_service.py').read_text(encoding='utf-8')
PHOTO = (ROOT / 'services' / 'photo_service.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_pricing_and_budget_config():
    # Gemini (the main photo engine) no longer carries a $0 unit price
    assert 'GEMINI_IMAGE_ESTIMATED_COST_USD = float(os.getenv("GEMINI_IMAGE_ESTIMATED_COST_USD", "0.02"))' in CONFIG
    # per-million LLM prices used when the provider does not report a bill
    assert 'LLM_USD_PER_M_INPUT = float(os.getenv("LLM_USD_PER_M_INPUT", "0.23"))' in CONFIG
    assert 'LLM_USD_PER_M_OUTPUT = float(os.getenv("LLM_USD_PER_M_OUTPUT", "0.96"))' in CONFIG
    assert 'GEMINI_LLM_USD_PER_M_INPUT = float(os.getenv("GEMINI_LLM_USD_PER_M_INPUT", "0.10"))' in CONFIG
    assert 'GEMINI_LLM_USD_PER_M_OUTPUT = float(os.getenv("GEMINI_LLM_USD_PER_M_OUTPUT", "0.40"))' in CONFIG
    assert 'LLM_REPORT_USAGE = os.getenv("LLM_REPORT_USAGE", "true")' in CONFIG
    # daily brakes, clamped non-negative, default sane
    assert 'SPEND_LLM_DAILY_BUDGET_USD = max(0.0, float(os.getenv("SPEND_LLM_DAILY_BUDGET_USD", "1.0")))' in CONFIG
    assert 'SPEND_IMAGE_DAILY_BUDGET_USD = max(0.0, float(os.getenv("SPEND_IMAGE_DAILY_BUDGET_USD", "2.0")))' in CONFIG


def test_spend_ledger_tables_exist():
    assert 'class LlmUsage(Base):' in MODELS
    assert '__tablename__ = "llm_usage"' in MODELS
    assert 'class ImageSpend(Base):' in MODELS
    assert '__tablename__ = "image_spend"' in MODELS
    # both are day-partitioned so /stats sums a single UTC day
    assert MODELS.count('day: Mapped[date] = mapped_column(Date, index=True, nullable=False)') >= 2


def test_spend_service_api():
    for fn in (
        'def estimate_llm_cost_usd(',
        'def record_llm_usage(',
        'def record_image_spend(',
        'def llm_cost_today(',
        'def image_cost_today(',
        'def llm_aux_allowed(',
        'def image_generation_allowed(',
        'def spend_snapshot(',
        'def format_spend_lines(',
    ):
        assert fn in SPEND, fn
    # the brake only ever touches mechanical helpers, never the visible reply
    assert "AUX_PURPOSES = frozenset({" in SPEND
    for aux in ('memory_extraction', 'adaptation_analysis', 'relationship_pulse', 'photo_idea', 'photo_reaction', 'rewrite'):
        assert f"'{aux}'" in SPEND, aux
    assert "'dialogue'" not in SPEND.split('AUX_PURPOSES')[1].split('}')[0]


def test_spend_service_budget_zero_means_off():
    # <= 0 disables the brake rather than shutting the product down
    assert 'if SPEND_LLM_DAILY_BUDGET_USD <= 0:' in SPEND
    assert 'if SPEND_IMAGE_DAILY_BUDGET_USD <= 0:' in SPEND


def test_spend_service_is_fail_silent():
    # a broken ledger must only lose the accounting, never take the bot down
    assert SPEND.count('except Exception:') >= 4
    assert 'logger.warning' in SPEND


def test_llm_usage_is_recorded_and_braked():
    assert 'from services import spend_service' in LLM
    assert 'def _record_usage(' in LLM
    # both provider legs log their spend on success
    assert LLM.count('_record_usage(purpose,') >= 2
    # the aux brake returns an empty result the callers already tolerate
    assert "return LLMResult('', 'budget', 'skipped')" in LLM
    assert 'if purpose in spend_service.AUX_PURPOSES and not spend_service.llm_aux_allowed():' in LLM
    # ask OpenRouter to report the real bill per call
    assert "extra['usage'] = {'include': True}" in LLM


def test_rewrite_no_longer_reuploads_the_whole_prompt():
    # V3.44.18 saving: the editor pass used to re-send the full fat dialogue
    # prompt (card + memories + 30 history msgs) just to reword one reply
    assert 'def _editor_instructions(' in CHAT
    assert 'async def _rewrite_if_needed(messages: list[dict], user_text: str, answer: str, character: dict | None = None)' in CHAT
    # the new prompt is a two-message editor pass, not `messages + [...]`
    assert 'rewrite_messages = messages +' not in CHAT
    # a braked/dead rewrite must never blank the message she sends
    assert 'if not r.text.strip():' in CHAT
    assert 'answer = await _rewrite_if_needed(messages, user_text, answer, character)' in CHAT


def test_image_spend_recorded_for_every_engine_leg():
    assert 'from services import spend_service' in PHOTO
    # fal (chat photos + studio + constructor avatars)
    assert "spend_service.record_image_spend(\n                        f'fal/{candidate}'" in PHOTO
    # Gemini ordinary frames + constructor avatar edit
    assert "record_image_spend('gemini_image', request.scene" in PHOTO
    assert "record_image_spend('gemini_image', 'constructor_avatar'" in PHOTO
    # OpenAI edit leg
    assert "record_image_spend('openai_image', request.scene" in PHOTO


def test_image_brake_sits_before_the_provider_and_refunds():
    # the routed set is gated up-front so the caller's refund path still pays back
    assert 'if not spend_service.image_generation_allowed():' in PHOTO
    assert "track_event(ensure_user(telegram_id), 'photo_budget_blocked'" in PHOTO
    assert "raise PhotoGenerationError('budget', 'daily_image_budget_exhausted')" in PHOTO


def test_stats_screen_renders_the_money_block():
    assert 'from services import spend_service' in MAIN
    assert 'spend_service.format_spend_lines(spend_service.spend_snapshot())' in MAIN
    assert '{spend_lines}' in MAIN
