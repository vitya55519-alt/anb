"""Bump version pins from 3.44.3 to 3.44.4 in test files."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TESTS = ROOT / 'tests'

def bump_file(path: Path) -> bool:
    text = path.read_text(encoding='utf-8')
    original = text
    # Widen version pins to include 3.44.4
    text = re.sub(r"VERSION in \('3\.44\.3'", "VERSION in ('3.44.4', '3.44.3'", text)
    text = re.sub(r"VERSION == '3\.44\.3'", "VERSION in ('3.44.4', '3.44.3')", text)
    if text != original:
        path.write_text(text, encoding='utf-8')
        return True
    return False

changed = 0
for f in TESTS.glob('*.py'):
    if bump_file(f):
        changed += 1
        print(f'  {f.name}')
print(f'\nBumped {changed} files')
