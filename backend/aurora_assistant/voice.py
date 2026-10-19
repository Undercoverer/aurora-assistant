"""One microphone owner; wake detection and STT have explicit audio gates."""
import threading
import time
from .config import require_assets
from .telemetry import event, content, phase


class Voice:
    def __init__(self, config, emit):
        import numpy as np
        import sounddevice as sd
        from openwakeword.model import Model
        from RealtimeSTT import AudioToTextRecorder
        from pathlib import Path
        require_assets(config)
        for key in ("embedding_model", "melspectrogram_model"):
            if not Path(config[key]).is_file():
                raise ValueError(f"Missing local asset: {key}")
        self.config, self.emit = config, emit
        self.lifecycle_lock = threading.Lock()
        self.closed = threading.Event()
        self.armed = threading.Event()
        self.awake = threading.Event()
        self.feeding = threading.Event()
        self.started = threading.Event()
        self.capture_error = None
        self.wake = Model(wakeword_models=[config["wake_model"]], inference_framework="onnx",
                          embedding_model_path=config["embedding_model"],
                          melspec_model_path=config["melspectrogram_model"])
        self._recorder_class = AudioToTextRecorder
        self._recorder_args = dict(
            model=config["model"], realtime_model_type=config["realtime_model"],
            transcription_engine="faster_whisper", device=config.get("device", "cpu"),
            compute_type=config.get("compute_type", "int8"), language=config.get("language", "en"),
            use_microphone=False, spinner=False, no_log_file=True,
            enable_realtime_transcription=True, realtime_processing_pause=0.15,
            silero_backend="raw_onnx", silero_onnx_model_path=config["silero_model"],
            silero_deactivity_detection=True,
            post_speech_silence_duration=config["silence_seconds"],
            faster_whisper_vad_filter=False,
            on_recording_start=self._started,
            on_transcription_start=self._finalizing,
            on_realtime_transcription_update=lambda text: emit("partial", text))
        self.recorder = self._recorder_class(**self._recorder_args)
        self.thread = threading.Thread(target=self._capture, args=(sd, np), daemon=True)
        self.thread.start()

    def _started(self):
        event("capture.speech_started")
        self.started.set()
        self.emit("state", "listening")

    def _finalizing(self, audio):
        event("capture.transcribing")
        self.feeding.clear()
        self.emit("state", "transcribing")

    def _capture(self, sd, np):
        try:
            with sd.RawInputStream(samplerate=16000, blocksize=1280, channels=1,
                                   dtype="int16", device=self.config.get("input_device")) as stream:
                while not self.closed.is_set():
                    data, overflow = stream.read(1280)
                    if overflow:
                        continue
                    pcm = bytes(data)
                    if self.feeding.is_set():
                        self.recorder.feed_audio(pcm)
                        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
                        self.emit("level", min(1., float(np.sqrt(np.mean(samples ** 2))) * 4))
                    elif self.armed.is_set():
                        scores = self.wake.predict(np.frombuffer(pcm, dtype=np.int16))
                        if max(scores.values(), default=0) >= self.config.get("wake_threshold", 0.5):
                            event("wake.detected")
                            self.armed.clear()
                            self.feeding.set()
                            self.emit("state", "wake")
                            self.awake.set()
        except Exception as exc:
            self.capture_error = exc
            self.awake.set()
            self.recorder.abort()

    def next(self, follow_up=False, follow_up_seconds=12):
        self.recorder.clear_audio_queue()
        self.wake.reset()
        self.started.clear()
        self.awake.clear()
        if follow_up:
            self.armed.clear()
            self.feeding.set()
            self.awake.set()
            self.emit('state', 'listening')
            event('capture.follow_up', timeout_seconds=follow_up_seconds)
        else:
            self.armed.set()
        while not self.awake.wait(0.2):
            if self.closed.is_set() or self.capture_error:
                break
        if self.capture_error:
            raise RuntimeError("Microphone capture failed") from self.capture_error
        if self.closed.is_set():
            return ""
        expired = threading.Event()
        timed_out = threading.Event()
        def watchdog():
            begin = time.monotonic()
            while not expired.wait(0.1):
                age = time.monotonic() - begin
                if ((not self.started.is_set() and age > (follow_up_seconds if follow_up else self.config.get("wake_timeout", 8)))
                        or age > self.config.get("max_utterance_seconds", 45)):
                    event("capture.timeout", elapsed_seconds=round(age, 2))
                    timed_out.set()
                    self.feeding.clear()
                    self.recorder.abort()
                    break
        guard = threading.Thread(target=watchdog, daemon=True)
        guard.start()
        try:
            with phase("stt.final"):
                text = self.recorder.text() or ""
            if self.capture_error:
                raise RuntimeError("Microphone capture failed during transcription") from self.capture_error
            return "" if timed_out.is_set() or self.closed.is_set() else text
        finally:
            expired.set()
            guard.join(timeout=1)
            self.armed.clear()
            self.feeding.clear()
            if timed_out.is_set() and not self.closed.is_set():
                # abort() can leave completed recordings in RealtimeSTT's internal
                # queue. Recreate it so cancelled audio cannot become a later turn.
                with self.lifecycle_lock:
                    if not self.closed.is_set():
                        self.recorder.shutdown()
                        self.recorder = self._recorder_class(**self._recorder_args)

    def close(self):
        self.closed.set()
        self.armed.clear()
        self.feeding.clear()
        self.awake.set()
        with self.lifecycle_lock:
            self.recorder.abort()
            self.thread.join(timeout=2)
            self.recorder.shutdown()
