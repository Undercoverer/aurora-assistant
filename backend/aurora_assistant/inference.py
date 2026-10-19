import asyncio
import io
import json
from .actions import schema


class Inference:
    def __init__(self, config):
        import httpx
        self.config = config
        # Do not inherit HTTP proxies or follow redirects to a remote service.
        self.http = httpx.AsyncClient(timeout=90, trust_env=False, follow_redirects=False)

    async def wait_ready(self):
        for attempt in range(60):
            try:
                llm = await self.http.get(self.config["llm"]["url"] + "/models", timeout=2)
                tts = await self.http.get(self.config["tts"]["url"].removesuffix("/v1") + "/health", timeout=2)
                llm.raise_for_status()
                tts.raise_for_status()
                names = {m["id"] for m in llm.json()["data"]}
                if self.config["llm"]["model"] not in names:
                    raise ValueError("Configured Ollama model is not installed")
                if tts.json().get("ready"):
                    return
            except ValueError:
                raise
            except Exception:
                pass
            await asyncio.sleep(1)
        raise RuntimeError("Local inference services are not ready")

    async def plan(self, text):
        c = self.config["llm"]
        response = await self.http.post(c["url"] + "/chat/completions", json={
            "model": c["model"], "stream": False, "temperature": 0,
            "max_tokens": 2048,
            "messages": [
                {"role": "system", "content":
                 "You are a local desktop assistant. Select only actions explicitly requested "
                 "by the user. Use only the supplied schema. If ambiguous, return no actions "
                 "and ask a short clarification. For questions, return no actions and a brief "
                 "answer. Never claim an action has succeeded. /no_think"},
                {"role": "user", "content": text[:8192]}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "desktop_plan", "strict": True, "schema": schema(self.config["apps"], self.config.get("dbus_actions", {}))}}})
        response.raise_for_status()
        return json.loads(response.json()["choices"][0]["message"]["content"])

    async def speak(self, text, level):
        import numpy as np
        import sounddevice as sd
        import soundfile as sf
        c = self.config["tts"]
        response = await self.http.post(c["url"] + "/audio/speech", json={
            "model": c["model"], "input": text[:1000], "voice": c["voice"],
            "response_format": "wav"})
        response.raise_for_status()
        samples, rate = sf.read(io.BytesIO(response.content), dtype="float32", always_2d=True)
        if len(samples) > rate * 120 or samples.shape[1] > 2:
            raise ValueError("Invalid synthesized audio length or channels")
        # Blocking writes pace the visual envelope against actual playback.
        stream = sd.OutputStream(samplerate=rate, channels=samples.shape[1], dtype="float32")
        try:
            await asyncio.to_thread(stream.start)
            block = max(1, rate // 30)
            for i in range(0, len(samples), block):
                chunk = samples[i:i + block]
                await level(min(1.0, float(np.sqrt(np.mean(chunk * chunk))) * 4))
                await asyncio.to_thread(stream.write, chunk)
        finally:
            await asyncio.to_thread(stream.stop)
            stream.close()
            await level(0)

    async def close(self):
        await self.http.aclose()
