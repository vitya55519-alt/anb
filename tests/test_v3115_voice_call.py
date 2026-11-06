"""V3.115.0: «📞 Позвонить» — Premium call (chat pipeline + her TTS voice, 18+)
and the free live call through Gemini Live."""
import asyncio
import json
import sys
import types as _pytypes
from pathlib import Path

from services import voice_call

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')
HTML = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')


def test_mode_premium_vs_live():
    assert voice_call.mode_for(True) == 'premium'
    assert voice_call.mode_for(False) == 'live'
    assert voice_call.mode_for(False, admin=True) == 'premium'
    assert voice_call.mode_for(False, admin=True, asked='live') == 'live'
    # a regular user cannot ask for the other call
    assert voice_call.mode_for(False, admin=False, asked='premium') == 'live'
    assert voice_call.mode_for(True, admin=False, asked='live') == 'premium'


def test_limits_defaults():
    assert voice_call.PREMIUM_SECONDS_PER_DAY == 15 * 60
    assert voice_call.FREE_SECONDS_PER_DAY == 180
    assert voice_call.LIVE_MODELS[0] == 'gemini-3.8-live'


def test_spoken_strips_actions_and_emoji():
    assert voice_call.spoken('*улыбается* привет, котик 😘))') == 'привет, котик'
    assert voice_call.spoken('ну…\n\nа ты?') == 'ну… а ты?'
    assert voice_call.spoken('') == ''


def test_premium_turn_seconds_capped():
    assert voice_call.premium_turn_seconds('t1', now=100.0) == 0.0
    assert voice_call.premium_turn_seconds('t1', now=110.0) == 10.0
    assert voice_call.premium_turn_seconds('t1', now=1000.0) == voice_call.MAX_TURN_GAP


def test_live_prompt_has_persona_memory_history_and_clean_rule():
    ch = {'name': 'Агата', 'age': 24, 'personality': {'core': ['нежная'], 'communication': {'tone': 'тихий шёпот'}}}
    p = voice_call.live_system_prompt(ch, 'Витя', ['любит кофе'], [('user', 'привет'), ('assistant', '*смеётся* хай 😘')])
    assert 'Агата' in p and 'Витя' in p and 'любит кофе' in p
    assert 'Ты: хай' in p
    assert 'без откровенного' in p
    assert 'live call' not in p.lower() or 'LIVE PHONE CALL' not in p  # RU rules by default
    assert 'LIVE PHONE CALL' in voice_call.live_system_prompt(ch, '', [], [], english=True)


def test_routes_and_gates():
    for route in ("'/webapp/api/call/info'", "'/webapp/api/call/turn'", "'/webapp/api/call/end'", "'/webapp/ws/call'"):
        assert route in MAIN
    # the call has its own minutes, not the daily message limit, but the same consent
    gate = MAIN[MAIN.index('def _call_gate'):MAIN.index('def _call_auth')]
    assert 'has_accepted' in gate and 'can_send_message' not in gate
    turn = MAIN[MAIN.index('async def _webapp_api_call_turn'):MAIN.index('async def _webapp_ws_call')]
    assert "mode != 'premium'" in turn and 'scene=scene' in turn
    ws = MAIN[MAIN.index('async def _webapp_ws_call'):MAIN.index('async def _webapp_api_call_end')]
    assert "mode != 'live'" in ws and 'GEMINI_API_KEY' in ws
    # the Gemini key never goes to the app
    assert 'GEMINI_API_KEY' not in HTML


def test_app_has_call_screen():
    for marker in ('id="chatCall"', 'id="callview"', 'id="callUpsell"', "'/webapp/ws/call?", "'/webapp/api/call/turn?",
                   'call_mode_prem', 'call_up_tx', 'createScriptProcessor', 'sampleRate / 16000', 'createBuffer(1, n, 24000)'):
        assert marker in HTML, marker


# ── the live bridge with a fake Gemini session ─────────────────────────────

class _Msg:
    def __init__(self, t, data):
        self.type, self.data = t, data


class _FakeWS:
    def __init__(self, incoming):
        self.sent_json, self.sent_bytes = [], []
        self._incoming = incoming

    async def send_json(self, j):
        self.sent_json.append(j)

    async def send_bytes(self, b):
        self.sent_bytes.append(b)

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self._incoming:
            await asyncio.sleep(0.01)
            yield m
        await asyncio.sleep(0.05)


def _install_fake_genai(monkeypatch, sent):
    from google.genai import types as gt

    def sc(**kw):
        return gt.LiveServerMessage(server_content=gt.LiveServerContent(**kw))

    script = [
        sc(model_turn=gt.Content(role='model', parts=[gt.Part(inline_data=gt.Blob(data=b'\x01\x00' * 4, mime_type='audio/pcm'))])),
        sc(output_transcription=gt.Transcription(text='Привет, ')),
        sc(output_transcription=gt.Transcription(text='котик')),
        sc(turn_complete=True),
        sc(input_transcription=gt.Transcription(text='как дела')),
        sc(turn_complete=True),
    ]

    class Session:
        async def send_client_content(self, **kw):
            sent.append(('text', kw['turns'].parts[0].text))

        async def send_realtime_input(self, **kw):
            sent.append(('audio', kw['audio'].data))

        async def receive(self):
            while script:
                yield script.pop(0)
            await asyncio.sleep(10)

    class Conn:
        async def __aenter__(self):
            return Session()

        async def __aexit__(self, *a):
            return False

    class Live:
        def connect(self, model, config):
            sent.append(('model', model))
            return Conn()

    class Client:
        def __init__(self, api_key):
            self.aio = _pytypes.SimpleNamespace(live=Live())

    import google.genai as genai
    monkeypatch.setattr(genai, 'Client', Client)


def test_live_bridge_relays_audio_and_transcript(monkeypatch):
    from aiohttp import WSMsgType
    sent = []
    _install_fake_genai(monkeypatch, sent)
    ws = _FakeWS([_Msg(WSMsgType.BINARY, b'\x00\x00' * 160), _Msg(WSMsgType.TEXT, json.dumps({'type': 'hangup'}))])
    seconds, transcript, reason = asyncio.run(voice_call.live_bridge(
        ws, api_key='k', voice_name='Kore', system_prompt='x', seconds_allowed=60))
    assert ('model', 'gemini-3.8-live') in sent
    assert ('text', voice_call.LIVE_HELLO) in sent
    assert any(k == 'audio' for k, _ in sent)
    assert ws.sent_json[0]['type'] == 'ready'
    assert ws.sent_bytes and ws.sent_bytes[0] == b'\x01\x00' * 4
    assert ('assistant', 'Привет, котик') in transcript
    assert reason == 'hangup' and seconds >= 0
