"""Local forced alignment and caption scheduling against the audio device clock."""
from collections import deque
import math
import re


def text_chunks(text, limit=180):
    """Keep exact text offsets, preferring sentence or whitespace boundaries."""
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            candidates = list(re.finditer(r'[.!?;]\s+|\s+', text[start:end]))
            if candidates:
                end = start + candidates[-1].end()
        yield start, text[start:end]
        start = end


def align_words(model, audio_bytes, text):
    import io
    from faster_whisper.audio import decode_audio, pad_or_trim
    from faster_whisper.tokenizer import Tokenizer
    audio = decode_audio(io.BytesIO(audio_bytes), sampling_rate=16000)
    if not 0 < len(audio) <= 30 * 16000:
        raise ValueError('Alignment chunk must fit one Whisper window')
    features = model.feature_extractor(audio)
    encoded = model.encode(pad_or_trim(features, 3000))
    tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual, task='transcribe', language='en')
    aligned = model.find_alignment(tokenizer, [tokenizer.encode(text)], encoded, len(audio) // 160)[0]
    marks, cursor = [], 0
    for word in aligned:
        value = word['word'].strip()
        if not value:
            continue
        at = text.find(value, cursor)
        if at < 0 or text[cursor:at].strip():
            raise ValueError('Alignment does not preserve the supplied text')
        cursor = at + len(value)
        marks.append({'start': float(word['start']), 'end': float(word['end']), 'charEnd': cursor})
    if not marks or text[cursor:].strip():
        raise ValueError('Incomplete word alignment')
    marks[-1]['charEnd'] = len(text)
    validate_marks(marks, text, len(audio) / 16000)
    return marks


def validate_marks(marks, text, duration):
    if not isinstance(marks, list) or not marks or len(marks) > 2000:
        raise ValueError('Invalid word timings')
    previous_time, previous_char = -1, 0
    for mark in marks:
        start, end, char = mark['start'], mark['end'], mark['charEnd']
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end)
                or not 0 <= start <= end <= duration + 0.05 or start < previous_time
                or type(char) is not int or not previous_char < char <= len(text)):
            raise ValueError('Invalid word timing bounds')
        previous_time, previous_char = start, char
    if previous_char != len(text):
        raise ValueError('Timings omit text')


class PlaybackClock:
    """Callback adds DAC anchors; the event loop reads the audible sample offset."""
    def __init__(self):
        self.anchors = deque(maxlen=512)

    def record(self, sample, dac_time, frames):
        self.anchors.append((sample, dac_time, frames))

    def position(self, device_time, rate):
        while len(self.anchors) > 1 and self.anchors[1][1] <= device_time:
            self.anchors.popleft()
        if not self.anchors or device_time < self.anchors[0][1]:
            return None
        sample, dac, frames = self.anchors[0]
        return sample / rate + min(frames / rate, max(0, device_time - dac))


async def play_audio(samples, rate, text, marks, level, message):
    import asyncio
    import numpy as np
    import sounddevice as sd
    clock = PlaybackClock()
    position = 0
    failed = False
    done = False

    def callback(out, frames, timing, status):
        nonlocal position, failed
        out.fill(0)
        if status.output_underflow:
            failed = True
            raise sd.CallbackAbort
        count = min(frames, len(samples) - position)
        out[:count] = samples[position:position + count]
        clock.record(position, timing.outputBufferDacTime, count)
        position += count
        if position >= len(samples):
            raise sd.CallbackStop

    def finished():
        nonlocal done
        done = True

    stream = sd.OutputStream(samplerate=rate, channels=samples.shape[1], dtype='float32',
                             callback=callback, finished_callback=finished, blocksize=0)
    index, shown = 0, ''
    try:
        if message:
            await message('')
        stream.start()
        async with asyncio.timeout(len(samples) / rate + 10):
            while not done:
                audible = clock.position(stream.time, rate)
                if audible is not None:
                    while index < len(marks) and marks[index]['start'] <= audible:
                        shown = text[:marks[index]['charEnd']]
                        index += 1
                    if message and shown:
                        await message(shown)
                        shown = ''
                    at = min(len(samples) - 1, int(audible * rate))
                    block = samples[at:at + max(1, rate // 30)]
                    await level(min(1., float(np.sqrt(np.mean(block * block))) * 4))
                await asyncio.sleep(1 / 30)
        if failed or position != len(samples):
            raise RuntimeError('Audio playback interrupted')
        if message:
            await message(text)
    finally:
        # Abort on cancellation; never leave queued speech running after a turn.
        stream.abort()
        stream.close()
        await level(0)
