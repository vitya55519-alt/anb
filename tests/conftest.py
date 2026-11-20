

import pytest as _pytest


@_pytest.fixture(autouse=True)
def _her_day_llm_path(request, monkeypatch):
    """V3.167.27: her-day push is a fixed text pool now; the older tests that
    exercise the LLM-written moment run with the pool switched off."""
    if request.node.fspath.basename != 'test_v316727_spicy_source_static.py':
        try:
            from services import life_event_service
            monkeypatch.setattr(life_event_service, 'HER_DAY_FIXED_POOL', False)
        except Exception:
            pass
    yield
