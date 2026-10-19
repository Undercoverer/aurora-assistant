"""Small OpenAI Audio Speech-compatible adapter; no asset downloads."""
import argparse
import asyncio
import io
from contextlib import asynccontextmanager
from .config import offline_environment


REQUEST_TIMEOUT = 10


class SpeechBusy(Exception):
    pass


async def run_exclusive(lock, work):
    """The worker owns the lock even if its HTTP caller is cancelled."""
    if lock.locked():
        raise SpeechBusy()
    await lock.acquire()
    async def finish():
        try:
            return await asyncio.to_thread(work)
        finally:
            lock.release()
    job = asyncio.create_task(finish())
    # Retrieve exceptions even when the HTTP caller has gone away.
    job.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    return await asyncio.shield(job)


def make_app(model_dir, model_name, alignment_model=None):
    from fastapi import FastAPI, HTTPException, Request, Response
    import soundfile as sf
    from supertonic import TTS
    engine = None
    aligner = None
    lock = asyncio.Lock()
    @asynccontextmanager
    async def lifespan(app):
        nonlocal engine, aligner
        engine = await asyncio.to_thread(TTS, model=model_name, model_dir=model_dir, auto_download=False)
        if alignment_model:
            from faster_whisper import WhisperModel
            aligner = await asyncio.to_thread(WhisperModel, alignment_model, device="cpu", compute_type="int8", local_files_only=True)
        yield
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health():
        return {"ready": engine is not None}

    @app.post("/v1/audio/speech")
    @app.post("/v1/audio/speech/timed")
    async def speech(request: Request):
        chunks = bytearray()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async for chunk in request.stream():
                    if len(chunks) + len(chunk) > 8192:
                        raise HTTPException(413, "Request too large")
                    chunks.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, "Request body timed out") from None
        import json
        try:
            body = json.loads(chunks)
            text, voice = body["input"], body.get("voice", "F1")
            if (not isinstance(text, str) or not text.strip() or not 0 < len(text) <= 1000
                    or body.get("model", model_name) != model_name
                    or body.get("response_format", "wav") != "wav"
                    or voice not in {f"{s}{i}" for s in "MF" for i in range(1, 6)}):
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(400, "Invalid speech request") from None
        if engine is None:
            raise HTTPException(503, "Speech engine is not ready")
        if lock.locked():
            raise HTTPException(429, "Speech engine busy")
        timed = request.url.path.endswith('/timed')
        def synthesize():
            style = engine.get_voice_style(voice_name=voice)
            import numpy as np
            from .speech_timing import text_chunks, align_words
            chunks_to_say = list(text_chunks(text)) if timed else [(0, text)]
            waves, marks, modes = [], [], []
            offset = 0.
            for char_offset, chunk in chunks_to_say:
                wave, _ = engine.synthesize(text=chunk, voice_style=style, lang="en")
                wave = wave.reshape(-1)
                if not len(wave) or not np.isfinite(wave).all():
                    raise ValueError('Speech engine produced empty or non-finite audio')
                duration = len(wave) / engine.sample_rate
                if offset + duration > 120:
                    raise ValueError("Synthesized response is too long")
                if timed:
                    buffer = io.BytesIO()
                    sf.write(buffer, wave, engine.sample_rate, format="WAV", subtype="PCM_16")
                    try:
                        if aligner is None:
                            raise ValueError("Alignment is disabled")
                        chunk_marks = align_words(aligner, buffer.getvalue(), chunk)
                        modes.append('aligned')
                    except Exception:
                        # Do not invent evenly spaced word timestamps.
                        chunk_marks = [{'start': 0., 'end': duration, 'charEnd': len(chunk)}]
                        modes.append('chunk')
                    marks.extend({'start': m['start'] + offset, 'end': m['end'] + offset,
                                  'charEnd': m['charEnd'] + char_offset} for m in chunk_marks)
                waves.append(wave)
                offset += duration
            out = io.BytesIO()
            sf.write(out, np.concatenate(waves), engine.sample_rate, format="WAV", subtype="PCM_16")
            return out.getvalue(), marks, modes
        try:
            audio, marks, modes = await run_exclusive(lock, synthesize)
        except SpeechBusy:
            raise HTTPException(429, "Speech engine busy") from None
        if timed:
            import base64
            return {"audio": base64.b64encode(audio).decode('ascii'), "format": "wav",
                    "text": text, "words": marks, "timing": modes}
        return Response(audio, media_type="audio/wav")
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--model", default="supertonic-3")
    parser.add_argument("--alignment-model", help="Installed CTranslate2 Whisper model for local word alignment")
    parser.add_argument("--port", type=int, default=7788)
    args = parser.parse_args()
    offline_environment()
    import uvicorn
    uvicorn.run(make_app(args.model_dir, args.model, args.alignment_model), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
