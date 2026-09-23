"""One-off: widen version pins in tests to include 3.44.3."""
from pathlib import Path

tests = Path(__file__).resolve().parent / 'tests'
changed = 0
for f in tests.glob('test_*.py'):
    text = f.read_text(encoding='utf-8')
    orig = text
    # "VERSION in ('3.43.7'" -> "VERSION in ('3.44.3', '3.43.7'"
    text = text.replace("VERSION in ('3.43.7'", "VERSION in ('3.44.3', '3.43.7'")
    # "VERSION == '3.43.7'" -> "VERSION in ('3.44.3', '3.43.7')"
    text = text.replace("VERSION == '3.43.7'", "VERSION in ('3.44.3', '3.43.7')")
    if text != orig:
        f.write_text(text, encoding='utf-8')
        changed += 1
print('changed files:', changed)
