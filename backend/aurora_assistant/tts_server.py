"""Small OpenAI Audio Speech-compatible adapter; no asset downloads."""
import argparse
import asyncio
import io
from contextlib import asynccontextmanager
from .config import offline_environment


def make_app(model_dir, model_name):
    from fastapi import FastAPI, HTTPException, Request, Response
    import soundfile as sf
    from supertonic import TTS
    engine = None
    lock = asyncio.Lock()
    @asynccontextmanager
    async def lifespan(app):
        nonlocal engine
        engine = await asyncio.to_thread(TTS, model=model_name, model_dir=model_dir, auto_download=False)
        yield
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health():
        return {"ready": engine is not None}

    @app.post("/v1/audio/speech")
    async def speech(request: Request):
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > 8192:
                raise HTTPException(413, "Request too large")
        import json
        try:
            body = json.loads(chunks)
            text, voice = body["input"], body.get("voice", "F1")
            if (not isinstance(text, str) or not 0 < len(text) <= 1000
                    or body.get("model", model_name) != model_name
                    or body.get("response_format", "wav") != "wav"
                    or voice not in {f"{s}{i}" for s in "MF" for i in range(1, 6)}):
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(400, "Invalid speech request") from None
        if lock.locked():
            raise HTTPException(429, "Speech engine busy")
        def synthesize():
            style = engine.get_voice_style(voice_name=voice)
            wave, _ = engine.synthesize(text=text, voice_style=style, lang="en")
            out = io.BytesIO()
            sf.write(out, wave.reshape(-1), engine.sample_rate, format="WAV", subtype="PCM_16")
            return out.getvalue()
        async with lock:
            audio = await asyncio.to_thread(synthesize)
        return Response(audio, media_type="audio/wav")
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--model", default="supertonic-3")
    parser.add_argument("--port", type=int, default=7788)
    args = parser.parse_args()
    offline_environment()
    import uvicorn
    uvicorn.run(make_app(args.model_dir, args.model), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
