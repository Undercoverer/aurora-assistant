import unittest
import httpx
from aurora_assistant.inference import Inference


class LocalHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_plan_schema_and_no_redirects(self):
        config = {"llm": {"url": "http://127.0.0.1:11434/v1", "model": "qwen3:4b"},
                  "tts": {"url": "http://127.0.0.1:7788/v1"}, "apps": {}}
        client = Inference(config)
        await client.http.aclose()
        seen = []
        def respond(request):
            import json
            seen.append(request)
            body = json.loads(request.content)
            self.assertEqual(body['response_format']['type'], 'json_schema')
            self.assertEqual(body['model'], 'qwen3:4b')
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"actions": [], "reply": "Hello"}'}}]})
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False, follow_redirects=False)
        try:
            self.assertEqual(await client.plan("hello"), {"actions": [], "reply": "Hello"})
            self.assertEqual(str(seen[0].url), "http://127.0.0.1:11434/v1/chat/completions")
        finally:
            await client.close()

    async def test_service_readiness_checks_model(self):
        config = {"llm": {"url": "http://127.0.0.1:11434/v1", "model": "qwen3:4b"},
                  "tts": {"url": "http://127.0.0.1:7788/v1"}, "apps": {}}
        client = Inference(config)
        await client.http.aclose()
        def respond(request):
            return httpx.Response(200, json={"data": []} if request.url.path == '/v1/models' else {"ready": True})
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            with self.assertRaisesRegex(ValueError, "not installed"):
                await client.wait_ready()
        finally:
            await client.close()
