"""V3.57.3 — every runtime source file must actually COMPILE, not just parse.

Owner pasted the Railway logs: the container was crash-looping on

    SyntaxError: name '_stt_good_model' is used prior to global declaration
      File "/app/services/voice_service.py", line 206, in _transcribe_gemini
      File "/app/main.py", line 132, in <module>
        from services.voice_service import transcribe, synthesize_bytes, VALID_VOICES

The whole app failed to import (the bot + Mini App never came up). The static
smoke test only ran ``ast.parse`` — that validates the GRAMMAR, but "a name is
used before its ``global`` declaration" is a symbol-table error that only the
full ``compile()`` surfaces. This test closes that blind spot for the runtime
package so a crash-loop can never ship green again. No DB, no network, no keys.
"""
import py_compile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# The directories Railway imports at boot; a SyntaxError in any of them is fatal.
_RUNTIME_DIRS = ('services', 'models', 'app')
_RUNTIME_FILES = [ROOT / 'main.py', ROOT / 'config.py']


def _runtime_sources():
    files = list(_RUNTIME_FILES)
    for d in _RUNTIME_DIRS:
        base = ROOT / d
        if base.exists():
            files.extend(sorted(base.rglob('*.py')))
    return [f for f in files if '__pycache__' not in f.parts]


@pytest.mark.parametrize('path', _runtime_sources(), ids=lambda p: p.name)
def test_runtime_module_compiles(path):
    # py_compile runs the same compile step as the interpreter import, so it
    # raises exactly the error that would crash the container on boot.
    try:
        py_compile.compile(str(path), cfile=str(path.with_suffix('.pyc.check')),
                           doraise=True, quiet=1)
    except py_compile.PyCompileError as exc:
        pytest.fail(f'{path} does not compile (Railway import would crash):\n{exc}')
    finally:
        probe = path.with_suffix('.pyc.check')
        if probe.exists():
            probe.unlink()


def test_gemini_stt_global_is_declared_before_first_use():
    # Regression pin for THIS crash: inside _transcribe_gemini the ``global``
    # statement must precede the models tuple that reads _stt_good_model.
    src = (ROOT / 'services' / 'voice_service.py').read_text(encoding='utf-8')
    body = src[src.index('async def _transcribe_gemini('):src.index('async def _transcribe_openai(')]
    assert body.index('global _stt_good_model') < body.index('_stt_good_model,) + _STT_MODEL_CHAIN'), \
        'global _stt_good_model must be declared before its first use in _transcribe_gemini'
