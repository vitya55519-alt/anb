"""V3.166.3: a route may not be registered against a handler that is gone.

V3.166.2 deleted the free-demo endpoint together with its neighbour
`_webapp_api_autopay`, left the `add_post` line in place and the service died
on startup with a NameError. The static text pins cannot see that, so this one
reads the route table out of the AST and resolves every handler by name.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_SRC = (ROOT / 'main.py').read_text(encoding='utf-8')
TREE = ast.parse(MAIN_SRC)


def _module_names(tree: ast.Module) -> set[str]:
    """Everything importable at module level, including names bound inside a
    top-level try/if block (the imports of this file live in one)."""
    names: set[str] = set()

    def bind(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(t.id for t in ast.walk(target) if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)

    for top in tree.body:
        bind(top)
        if isinstance(top, (ast.If, ast.Try)):
            for sub in ast.walk(top):
                bind(sub)
    return names


def _route_handlers(tree: ast.Module) -> list[tuple[int, str]]:
    """(line, handler name) for every `app.router.add_get/add_post(...)` call."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        receiver = node.func.value
        if not (node.func.attr.startswith('add_') and getattr(receiver, 'attr', '') == 'router'):
            continue
        for arg in node.args[1:]:
            if isinstance(arg, ast.Name):
                found.append((node.lineno, arg.id))
    return found


def test_every_route_handler_resolves():
    names = _module_names(TREE)
    handlers = _route_handlers(TREE)
    assert len(handlers) > 100, f'only {len(handlers)} routes parsed — the probe broke'
    assert sorted({n for _, n in handlers if n not in names}) == []


def test_the_autopay_route_keeps_its_handler():
    # The one that regressed: the shop card's «🔁 Автопродление» link.
    assert 'async def _webapp_api_autopay(' in MAIN_SRC
    assert "add_post('/webapp/api/autopay', _webapp_api_autopay)" in MAIN_SRC


def test_the_demo_endpoint_stays_deleted():
    # V3.166.2: the free demo is gone for good — pinning both halves so a
    # future edit removes neither the handler nor its route in isolation.
    assert '_webapp_api_demo' not in MAIN_SRC
    assert "'/webapp/api/demo'" not in MAIN_SRC
