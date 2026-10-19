"""Regression cases from the adversarial review; no desktop or models required."""
import asyncio
import gzip
import io
import unittest
from unittest.mock import patch, AsyncMock, Mock
import httpx
from aurora_assistant.approval import Approval
from aurora_assistant.config import local_url
from aurora_assistant.inference import Inference
from aurora_assistant.settings import BusAccess, typed


class ValidationAttacks(unittest.TestCase):
    def test_scope_component_boundaries(self):
        bus = BusAccess({})
        for name in ('org.freedesktop.UPowerEvil', 'org.freedesktop.UPower2'):
            self.assertFalse(bus.allowed('system', name))
        self.assertTrue(bus.allowed('system', 'org.freedesktop.UPower'))
        self.assertTrue(bus.allowed('system', 'org.freedesktop.UPower.Child'))
        self.assertTrue(bus.allowed('session', 'org.kde.KWin'))
        self.assertFalse(BusAccess({'sessionPrefixes': ['']}).allowed('session', 'anything'))

    def test_malformed_loopback_urls(self):
        for value in (None, 12, 'http://127.0.0.1:65536/v1', 'http://127.0.0.1:abc',
                      'http://127.0.0.1:', 'http://127.0.0.1:0', 'http://@127.0.0.1',
                      'http://127.0.0.1/\nremote', 'http://[::1', 'http:///v1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                local_url(value)
        self.assertEqual(local_url('http://[::1]:8080/v1/'), 'http://[::1]:8080/v1')

    def test_boolean_numeric_coercion(self):
        for signature, value in [('ay', [True]), ('d', True), ('aay', [[False]])]:
            with self.subTest(signature=signature), self.assertRaises(ValueError):
                typed(signature, value)
        self.assertEqual(typed('ay', [0, 255]), b'\x00\xff')

    def test_malformed_approval_command(self):
        with self.assertRaises(ValueError):
            Approval().dispatch({'command': [], 'id': 'x'})


class AsyncAttacks(unittest.IsolatedAsyncioTestCase):
    async def client(self, handler):
        client = Inference({})
        await client.http.aclose()
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.close)
        return client

    async def test_response_size_limit(self):
        client = await self.client(lambda request: httpx.Response(200, content=b'x' * 65537))
        with self.assertRaisesRegex(ValueError, 'size limit'):
            await client.request('GET', 'http://127.0.0.1/', max_bytes=65536)

    async def test_compressed_response_decodes_once(self):
        client = await self.client(lambda request: httpx.Response(200,
            content=gzip.compress(b'{"ok":true}'), headers={'Content-Encoding': 'gzip'}))
        response = await client.request('GET', 'http://127.0.0.1/')
        self.assertEqual(response.json(), {'ok': True})

    async def test_slow_drip_has_total_deadline(self):
        class Slow(httpx.AsyncByteStream):
            async def __aiter__(self):
                while True:
                    await asyncio.sleep(.005)
                    yield b'x'
        client = await self.client(lambda request: httpx.Response(200, stream=Slow()))
        with self.assertRaises(TimeoutError):
            await client.request('GET', 'http://127.0.0.1/', timeout=.03)

    async def test_stalled_approval_notification_expires(self):
        approval = Approval()
        async def notify(_):
            await asyncio.Event().wait()
        self.assertFalse(await approval.request({}, notify, timeout=.02))
        self.assertIsNone(approval.pending)
        self.assertTrue(approval.future.done())

    async def test_approval_id_cannot_be_overridden(self):
        approval = Approval()
        async def notify(_):
            self.assertNotEqual(approval.pending['id'], 'chosen')
            approval.dispatch({'command': 'deny', 'id': approval.pending['id']})
        self.assertFalse(await approval.request({'id': 'chosen'}, notify))

    async def test_multichannel_audio_rejected_before_decode(self):
        import numpy as np
        import soundfile as sf
        audio = io.BytesIO()
        sf.write(audio, np.zeros((20, 3)), 24000, format='WAV')
        client = await self.client(lambda request: httpx.Response(200, content=audio.getvalue()))
        client.config = {'tts': {'url': 'http://127.0.0.1/v1', 'model': 'tts', 'voice': 'F1'}}
        with patch.object(sf.SoundFile, 'read', side_effect=AssertionError('must not decode')):
            with self.assertRaisesRegex(ValueError, 'channels'):
                await client.speak('hello', None)

    async def test_nan_audio_rejected_before_playback(self):
        import numpy as np
        import soundfile as sf
        audio = io.BytesIO()
        sf.write(audio, np.array([float('nan')]), 24000, format='WAV', subtype='FLOAT')
        client = await self.client(lambda request: httpx.Response(200, content=audio.getvalue()))
        client.config = {'tts': {'url': 'http://127.0.0.1/v1', 'model': 'tts', 'voice': 'F1'}}
        with self.assertRaisesRegex(ValueError, 'samples'):
            await client.speak('hello', None)


class OutcomeAttacks(unittest.IsolatedAsyncioTestCase):
    async def test_speech_failure_preserves_completed_action_result(self):
        from aurora_assistant.controller import Controller
        overlay, inference = AsyncMock(), AsyncMock()
        inference.speak.side_effect = RuntimeError('audio device disconnected')
        agent = Mock(failed=False)
        agent.run = AsyncMock(return_value='Playback paused.')
        controller = Controller(overlay, inference, AsyncMock(), {}, agent=agent)
        with patch('aurora_assistant.controller.asyncio.sleep', new_callable=AsyncMock):
            await controller.handle('Pause playback')
        overlay.message.assert_any_await('Playback paused. Speech output is unavailable.')
        overlay.state.assert_any_await('success')
        agent.run.assert_awaited_once()


class ManifestAttacks(unittest.TestCase):
    def test_empty_traversal_and_invalid_digest_manifests(self):
        import json
        import tempfile
        from pathlib import Path
        from aurora_assistant.models import check, spec_hash
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / 'current'
            current.mkdir()
            for entries in ({}, {'../outside': '0' * 64}, {'model': 'garbage'}):
                (current / 'manifest.json').write_text(json.dumps({
                    'spec_hash': spec_hash({}), 'files': entries}))
                with self.subTest(entries=entries), self.assertRaises(ValueError):
                    check({}, directory)

    def test_manifest_symlink_escape(self):
        import json
        import tempfile
        from pathlib import Path
        from aurora_assistant.models import check, spec_hash
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'current').mkdir()
            (root / 'outside').write_bytes(b'not-a-model')
            (root / 'current/model').symlink_to(root / 'outside')
            (root / 'current/manifest.json').write_text(json.dumps({
                'spec_hash': spec_hash({}), 'files': {'model': '0' * 64}}))
            with self.assertRaisesRegex(ValueError, 'escapes'):
                check({}, root)


class PlanAttacks(unittest.TestCase):
    def test_nonstring_action_names_fail_validation(self):
        from aurora_assistant.actions import validate
        for name in ([], {}, True, None, 5):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate({'actions': [{'name': name, 'argument': None}], 'reply': ''}, {}, settings=True)


class ConfigAttacks(unittest.TestCase):
    def test_boolean_silence_is_not_a_duration(self):
        import json
        import tempfile
        from pathlib import Path
        from aurora_assistant.config import load
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'llm': {'url': 'http://127.0.0.1'},
                'tts': {'url': 'http://127.0.0.1'}, 'stt': {'silence_seconds': True}, 'apps': {}}))
            with self.assertRaisesRegex(ValueError, 'silence_seconds'):
                load(path)


class SocketPathAttacks(unittest.IsolatedAsyncioTestCase):
    async def test_symlinked_control_directory_is_rejected(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target'
            target.mkdir(mode=0o755)
            alias = root / 'aurora-assistant'
            alias.symlink_to(target, target_is_directory=True)
            with patch('aurora_assistant.approval.socket_path', return_value=alias / 'control.sock'):
                with self.assertRaises(ValueError):
                    await Approval().start()
            self.assertEqual(target.stat().st_mode & 0o777, 0o755)
