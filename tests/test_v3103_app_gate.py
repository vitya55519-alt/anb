"""V3.103.0 — the app-chat gate really blocks.

aiohttp < 3.11 (pinned by aiogram 3.15) has no StreamResponse.__bool__ and
its __len__ is 0, so ``if gate:`` was always False: the daily limit, the
18+ consent and the locked-card checks of the Mini App chat never stopped
anyone (backup 5 Nov: 1905 «sleep blocks» answered anyway).
"""
import ast
from pathlib import Path

MAIN = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')


def test_gate_checked_against_none():
    tree = ast.parse(MAIN)
    guarded = []
    for function in tree.body:
        if not isinstance(function, ast.AsyncFunctionDef):
            continue
        calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == 'to_thread'
                 and node.args and isinstance(node.args[0], ast.Name)
                 and node.args[0].id == '_webapp_chat_gate']
        if not calls:
            continue
        guarded.append(function.name)
        checks = [node for node in ast.walk(function) if isinstance(node, ast.If)
                  and any(isinstance(child, ast.Return)
                          and isinstance(child.value, ast.Name) and child.value.id == 'gate'
                          for child in node.body)]
        assert checks
        for check in checks:
            assert any(isinstance(node, ast.Compare)
                       and isinstance(node.left, ast.Name) and node.left.id == 'gate'
                       and len(node.ops) == 1 and isinstance(node.ops[0], ast.IsNot)
                       and isinstance(node.comparators[0], ast.Constant)
                       and node.comparators[0].value is None
                       for node in ast.walk(check.test))
    assert set(guarded) == {'_webapp_api_chat_send', '_webapp_api_chat_action',
                            '_webapp_api_chat_voice', '_webapp_api_chat_photo'}
    assert not any(isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                   and node.test.id == 'gate' for node in ast.walk(tree))
