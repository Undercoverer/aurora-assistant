import threading
import unittest
from unittest.mock import Mock
from aurora_assistant.voice import Voice


class GateTests(unittest.TestCase):
    def bare_voice(self):
        voice = Voice.__new__(Voice)
        for field in ('closed', 'armed', 'awake', 'feeding', 'started'):
            setattr(voice, field, threading.Event())
        voice.lifecycle_lock = threading.Lock()
        voice.emit = Mock()
        voice.config = {'wake_timeout': 0.02, 'max_utterance_seconds': 0.1}
        voice.capture_error = None
        voice.wake = Mock()
        voice.recorder = Mock()
        voice._recorder_class = Mock(return_value=Mock())
        voice._recorder_args = {}
        return voice

    def test_transcription_callback_accepts_audio_and_closes_gate(self):
        voice = self.bare_voice()
        voice.feeding.set()
        # RealtimeSTT 1.1.2 passes the complete audio array to this callback.
        self.assertIsNone(voice._finalizing(b'audio'))
        self.assertFalse(voice.feeding.is_set())
        voice.emit.assert_called_once_with('state', 'transcribing')

    def test_timeout_discards_text_and_recycles_cancelled_queue(self):
        voice = self.bare_voice()
        old = voice.recorder
        interrupted = threading.Event()
        old.abort.side_effect = interrupted.set
        def text():
            interrupted.wait(2)
            return 'cancelled text that must not execute'
        old.text.side_effect = text
        def wake():
            self.assertTrue(voice.armed.wait(1))
            voice.feeding.set()
            voice.awake.set()
        thread = threading.Thread(target=wake)
        thread.start()
        self.assertEqual(voice.next(), '')
        thread.join(1)
        self.assertFalse(voice.feeding.is_set())
        old.shutdown.assert_called_once()
        voice._recorder_class.assert_called_once_with()

    def test_microphone_failure_is_not_an_empty_successful_turn(self):
        voice = self.bare_voice()
        voice.capture_error = RuntimeError('device removed')
        with self.assertRaisesRegex(RuntimeError, 'Microphone capture failed'):
            voice.next()


class CaptureTests(unittest.TestCase):
    bare_voice = GateTests.bare_voice

    def capture(self, voice, pcm, overflow=False):
        import numpy as np
        from unittest.mock import patch
        stream = Mock()
        stream.device = 7
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        def read(_):
            voice.closed.set()
            return pcm, overflow
        stream.read.side_effect = read
        sd = Mock()
        sd.RawInputStream.return_value = stream
        with patch('aurora_assistant.voice.event') as events, patch(
                'aurora_assistant.voice.time.monotonic', side_effect=[0, 6, 6]):
            voice._capture(sd, np)
        return events

    def test_overflow_block_can_still_trigger_wake_word(self):
        voice = self.bare_voice()
        voice.armed.set()
        voice.wake.predict.return_value = {'wake': .9}
        events = self.capture(voice, b'\x00\x10' * 1280, overflow=True)
        self.assertIsNone(voice.capture_error)
        self.assertTrue(voice.awake.is_set())
        self.assertTrue(voice.feeding.is_set())
        health = next(call.kwargs for call in events.call_args_list if call.args == ('capture.health',))
        self.assertEqual(health['overflows'], 1)
        self.assertEqual(health['max_wake_score'], .9)
        self.assertGreater(health['max_rms'], 0)

    def test_silent_audio_is_visible_without_false_wake(self):
        voice = self.bare_voice()
        voice.armed.set()
        voice.wake.predict.return_value = {'wake': .001}
        events = self.capture(voice, b'\x00\x00' * 1280)
        health = next(call.kwargs for call in events.call_args_list if call.args == ('capture.health',))
        self.assertEqual(health['max_rms'], 0)
        self.assertTrue(health['armed'])
        self.assertFalse(voice.awake.is_set())

    def test_capture_exception_is_reported_and_unblocks_waiter(self):
        from unittest.mock import patch
        voice = self.bare_voice()
        voice.armed.set()
        voice.wake.predict.side_effect = ValueError('bad model output')
        with patch('aurora_assistant.voice.failure') as failed:
            self.capture(voice, b'\x00\x10' * 1280)
        self.assertIsInstance(voice.capture_error, ValueError)
        self.assertTrue(voice.awake.is_set())
        voice.recorder.abort.assert_called_once()
        self.assertEqual(failed.call_args.args[0], 'capture.failed')
