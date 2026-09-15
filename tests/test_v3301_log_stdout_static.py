"""V3.30.1 static pins: logs go to stdout, noisy loggers silenced.

Railway marks every stderr line as severity=error, and Python logging
writes to stderr by default — so the console showed plain INFO
apscheduler/aiogram lines as "errors". The log now streams to stdout, and
the 30-second reminder tick plus the per-update aiogram lines stay silent
unless something actually warns.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_version_bumped():
    assert VERSION in ('3.30.0', '3.30.1', '3.30.2', '3.30.3', '3.30.4', '3.30.5', '3.30.6', '3.30.7', '3.30.8', '3.30.9', '3.31.0', '3.31.1', '3.31.2', '3.31.3', '3.31.4', '3.31.5', '3.31.6', '3.31.7', '3.31.8', '3.32.0', '3.32.1', '3.33.0', '3.33.1', '3.34.0', '3.34.1', '3.35.0', '3.36.0', '3.37.0', '3.38.0')


def test_logging_streams_to_stdout():
    assert 'import sys' in MAIN
    assert 'stream=sys.stdout,' in MAIN
    assert 'logging.basicConfig(' in MAIN


def test_noisy_loggers_silenced():
    assert "logging.getLogger('apscheduler').setLevel(logging.WARNING)" in MAIN
    assert "logging.getLogger('aiogram.event').setLevel(logging.WARNING)" in MAIN
