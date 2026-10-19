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

    async def test_kev_route_uses_separate_model_and_rejects_bad_arguments(self):
        import json
        config = {'apps': {}, 'llm': {'url': 'http://127.0.0.1:11434/v1', 'model': 'large'},
                  'kev': {'enable': True, 'model': 'small'}}
        client = Inference(config)
        await client.http.aclose()
        answers = [
            {'actions': [{'name': 'volume', 'argument': 200}], 'reply': '', 'escalate': False},
            {'actions': [], 'reply': '', 'escalate': True},
            {'actions': [{'name': 'mute', 'argument': True}], 'reply': '', 'escalate': False}]
        def respond(request):
            data = json.loads(request.content)
            self.assertEqual(data['model'], 'small')
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answers.pop(0))}}]})
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            with self.assertRaises(ValueError):
                await client.quick_plan('volume')
            self.assertIsNone(await client.quick_plan('unknown'))
            self.assertEqual((await client.quick_plan('mute'))['actions'][0]['argument'], True)
        finally:
            await client.close()
