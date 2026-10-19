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

    async def test_kev_uses_systemone_and_rejects_uncertain_choice(self):
        import json
        from aurora_assistant.kev import MODEL
        config = {'apps': {}, 'llm': {'url': 'http://127.0.0.1:11434/v1', 'model': 'large'},
                  'kev': {'enable': True, 'model': MODEL, 'url': 'http://127.0.0.1:8008'}}
        client = Inference(config)
        await client.http.aclose()
        probabilities = [.5, .99]
        def respond(request):
            self.assertEqual(request.url.path, '/v1/systemone')
            data = json.loads(request.content)
            self.assertEqual(data['model'], MODEL)
            self.assertNotIn('messages', data)
            score = probabilities.pop(0)
            return httpx.Response(200, json={'answers': {'route': {'choice': 'apply',
                'probabilities': {'apply': score, 'escalate': 1-score}}}})
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            self.assertIsNone(await client.quick_plan('raise the volume to 200'))
            self.assertIsNone(await client.quick_plan('mute the speakers'))
            self.assertEqual((await client.quick_plan('mute the speakers'))['actions'][0]['argument'], True)
        finally:
            await client.close()
