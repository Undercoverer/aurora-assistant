import asyncio
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from aurora_assistant.config import load
from aurora_assistant.tts_server import run_exclusive, SpeechBusy


class CaptureFailureTests(unittest.TestCase):
    def voice(self):
        import test_voice
        voice = test_voice.GateTests().bare_voice()
        voice.config = {'wake_timeout': 5, 'max_utterance_seconds': 10}
        def wake():
            voice.armed.wait(2)
            voice.awake.set()
        thread = threading.Thread(target=wake)
        thread.start()
        self.addCleanup(thread.join, 2)
        return voice

    def test_capture_failure_during_transcription_discards_text(self):
        voice = self.voice()
        def text():
            voice.capture_error = RuntimeError('unplugged')
            return 'mute speakers'
        voice.recorder.text.side_effect = text
        with self.assertRaisesRegex(RuntimeError, 'during transcription'):
            voice.next()
        self.assertFalse(voice.feeding.is_set())

    def test_closed_capture_does_not_return_command(self):
        voice = self.voice()
        def text():
            voice.closed.set()
            return 'mute speakers'
        voice.recorder.text.side_effect = text
        self.assertEqual(voice.next(), '')


class SynthesisCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_http_caller_does_not_release_worker_lock(self):
        lock = asyncio.Lock()
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        def work():
            started.set()
            release.wait(2)
            finished.set()
            return 'audio'
        request = asyncio.create_task(run_exclusive(lock, work))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
            self.assertTrue(lock.locked())
            with self.assertRaises(SpeechBusy):
                await run_exclusive(lock, lambda: 'overlap')
        finally:
            release.set()
            await asyncio.to_thread(finished.wait, 2)
        # Acquiring the lock also waits for the worker's finally block.
        async with asyncio.timeout(2):
            async with lock:
                pass
        self.assertEqual(await run_exclusive(lock, lambda: 'next'), 'next')

    async def test_synthesis_error_releases_lock(self):
        lock = asyncio.Lock()
        def fail():
            raise ValueError('bad synthesis')
        with self.assertRaises(ValueError):
            await run_exclusive(lock, fail)
        self.assertEqual(await run_exclusive(lock, lambda: 'next'), 'next')


class ConfigurationMatrixTests(unittest.TestCase):
    def setUp(self):
        import os
        fixture = os.environ.get('AURORA_TEST_CONFIG', str(Path(__file__).resolve().parents[1] / 'config/assistant.example.json'))
        self.config = json.loads(Path(fixture).read_text())

    def load_config(self, config):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps(config))
            return load(path)

    def test_documented_example_is_valid(self):
        self.load_config(self.config)

    def test_invalid_ranges_and_policy_types(self):
        cases = [('stt', 'wake_threshold', x) for x in (0, -1, 2, True, float('nan'))]
        cases += [('stt', 'wake_timeout', x) for x in (0, 61, True, float('inf'))]
        cases += [('stt', 'max_utterance_seconds', x) for x in (0, 301, False)]
        cases += [(section, 'enable', x) for section in ('settings', 'kev', 'safety', 'webSearch') for x in ('false', 0, None)]
        cases += [('settings', 'maxRounds', x) for x in (0, 9, 2.5, True)]
        cases += [('kev', 'maxRounds', x) for x in (0, 5, True)]
        cases += [('tts', 'wordSync', 'false'), ('settings', 'sessionPrefixes', 'org.kde.'),
                  ('settings', 'systemPrefixes', [None]), ('webSearch', 'url', 'https://remote.example')]
        for section, key, value in cases:
            config = copy.deepcopy(self.config)
            config[section][key] = value
            with self.subTest(section=section, key=key, value=value), self.assertRaises(ValueError):
                self.load_config(config)

    def test_valid_numeric_boundaries(self):
        for section, key, values in [('stt', 'wake_threshold', (.01, 1)),
            ('stt', 'wake_timeout', (1, 60)), ('stt', 'max_utterance_seconds', (5, 300)),
            ('settings', 'maxRounds', (1, 8)), ('kev', 'maxRounds', (1, 4))]:
            for value in values:
                config = copy.deepcopy(self.config)
                config[section][key] = value
                with self.subTest(section=section, key=key, value=value):
                    self.load_config(config)


class SpeechHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import sys
        import httpx
        from unittest.mock import Mock, patch
        from aurora_assistant.tts_server import make_app
        import numpy as np
        self.engine = Mock(sample_rate=24000)
        self.engine.synthesize.return_value = (np.zeros(2400), None)
        with patch.dict(sys.modules, {'supertonic': Mock(TTS=Mock(return_value=self.engine))}):
            self.app = make_app('/unused', 'test')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://127.0.0.1')
        self.addAsyncCleanup(self.client.aclose)

    async def test_stalled_request_body_times_out(self):
        from unittest.mock import patch
        async def body():
            yield b'{'
            await asyncio.Event().wait()
        with patch('aurora_assistant.tts_server.REQUEST_TIMEOUT', .01):
            response = await self.client.post('/v1/audio/speech', content=body())
        self.assertEqual(response.status_code, 408)

    async def test_oversize_request_is_rejected(self):
        response = await self.client.post('/v1/audio/speech', content=b'x' * 8193)
        self.assertEqual(response.status_code, 413)

    async def test_whitespace_speech_is_rejected(self):
        response = await self.client.post('/v1/audio/speech', json={'input': ' \n ', 'model': 'test'})
        self.assertEqual(response.status_code, 400)

    async def test_unready_engine_returns_service_unavailable(self):
        response = await self.client.post('/v1/audio/speech', json={'input': 'hello', 'model': 'test'})
        self.assertEqual(response.status_code, 503)

    async def test_ready_engine_generates_valid_timed_audio(self):
        import base64
        import io
        import soundfile as sf
        async with self.app.router.lifespan_context(self.app):
            response = await self.client.post('/v1/audio/speech/timed', json={'input': 'hello', 'model': 'test'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        samples, rate = sf.read(io.BytesIO(base64.b64decode(data['audio'])))
        self.assertEqual((len(samples), rate), (2400, 24000))
        self.assertEqual(data['words'], [{'start': 0., 'end': .1, 'charEnd': 5}])
        self.assertEqual(data['timing'], ['chunk'])

    async def test_invalid_synthesis_samples_rejected_before_wav_encoding(self):
        import numpy as np
        async with self.app.router.lifespan_context(self.app):
            for wave in (np.array([]), np.array([float('nan')]), np.array([float('inf')])):
                self.engine.synthesize.return_value = (wave, None)
                with self.subTest(wave=wave), self.assertRaisesRegex(ValueError, 'empty or non-finite'):
                    await self.client.post('/v1/audio/speech', json={'input': 'hello', 'model': 'test'})
