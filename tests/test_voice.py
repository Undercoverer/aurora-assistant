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
