import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import httpx
from aurora_assistant.models import install_gguf, provision
from aurora_assistant.inference import Inference


class GGUFTests(unittest.TestCase):
    def test_download_uses_resolved_commit_and_exact_quantization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.gguf'
            source.write_bytes(b'GGUFtest')
            api = Mock()
            api.model_info.return_value = SimpleNamespace(sha='fixed-commit')
            api.list_repo_files.return_value = ['Qwen3-4B-Q4_K_M.gguf', 'Qwen3-4B-IQ4_K_M.gguf']
            with patch('huggingface_hub.HfApi', return_value=api), patch('huggingface_hub.hf_hub_download', return_value=str(source)) as download:
                result = install_gguf('hf.co/Qwen/Qwen3-4B-GGUF:Q4_K_M', 'pinned', root / 'planner.gguf')
            api.model_info.assert_called_once_with('Qwen/Qwen3-4B-GGUF', revision='pinned')
            download.assert_called_once_with('Qwen/Qwen3-4B-GGUF', filename='Qwen3-4B-Q4_K_M.gguf', revision='fixed-commit')
            self.assertEqual(result['revision'], 'fixed-commit')
            self.assertEqual((root / 'planner.gguf').read_bytes(), b'GGUFtest')

    def test_ambiguous_missing_and_split_models_fail_before_download(self):
        api = Mock()
        api.model_info.return_value = SimpleNamespace(sha='fixed')
        for files in ([], ['x-Q4_K_M-00001-of-00002.gguf', 'x-Q4_K_M-00002-of-00002.gguf'], ['x-IQ4_K_M.gguf']):
            api.list_repo_files.return_value = files
            with patch('huggingface_hub.HfApi', return_value=api), patch('huggingface_hub.hf_hub_download') as download:
                with self.assertRaisesRegex(ValueError, 'exactly one'):
                    install_gguf('hf.co/owner/model:Q4_K_M', None, Path('unused'))
                download.assert_not_called()

    def test_bad_header_does_not_install_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'bad'
            source.write_bytes(b'<html>failure</html>')
            api = Mock()
            api.model_info.return_value = SimpleNamespace(sha='fixed')
            api.list_repo_files.return_value = ['x-Q4_K_M.gguf']
            with patch('huggingface_hub.HfApi', return_value=api), patch('huggingface_hub.hf_hub_download', return_value=str(source)):
                with self.assertRaisesRegex(ValueError, 'GGUF header'):
                    install_gguf('hf.co/owner/model:Q4_K_M', None, root / 'planner.gguf')
            self.assertFalse((root / 'planner.gguf').exists())

    def test_cached_generation_needs_no_server_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            spec = {'plannerModel': 'hf.co/owner/model:Q4_K_M'}
            def install(spec, stage):
                (stage / 'planner.gguf').write_bytes(b'GGUFtest')
                return {'planner': {'revision': 'fixed'}}
            provision(spec, directory, installer=install)
            with patch('httpx.Client', side_effect=AssertionError('Unexpected HTTP')), patch('huggingface_hub.HfApi', side_effect=AssertionError('Unexpected download')):
                provision(spec, directory, installer=Mock(side_effect=AssertionError('Unexpected install')))


class PlannerAPITests(unittest.IsolatedAsyncioTestCase):
    async def test_readiness_accepts_exact_llama_alias_without_latest_suffix(self):
        config = {'llm': {'url': 'http://127.0.0.1:8009/v1', 'model': 'local-planner'},
                  'tts': {'url': 'http://127.0.0.1:7788/v1'}, 'apps': {},
                  'safety': {'enable': True, 'backend': 'planner', 'model': 'local-planner'}}
        client = Inference(config)
        await client.http.aclose()
        def respond(request):
            return httpx.Response(200, json={'data': [{'id': 'local-planner'}]} if request.url.path == '/v1/models' else {'ready': True})
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            await client.wait_ready()
        finally:
            await client.close()

    async def test_schema_request_targets_planner_alias(self):
        model = 'hf.co/Qwen/Qwen3-4B-GGUF:Q4_K_M'
        client = Inference({'llm': {'url': 'http://127.0.0.1:8009/v1', 'model': model}, 'apps': {}})
        await client.http.aclose()
        def respond(request):
            self.assertEqual(request.url.port, 8009)
            body = json.loads(request.content)
            self.assertEqual(body['model'], model)
            self.assertEqual(body['response_format']['type'], 'json_schema')
            return httpx.Response(200, json={'choices': [{'message': {'content': '{"actions":[],"reply":"Which device?"}'}}]})
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            self.assertEqual((await client.plan('mute it'))['reply'], 'Which device?')
        finally:
            await client.close()

class RouterReadinessTests(unittest.IsolatedAsyncioTestCase):
    def config(self):
        return {'llm': {'url': 'http://127.0.0.1:8008/v1', 'model': 'planner'},
                'tts': {'url': 'http://127.0.0.1:7788/v1'}, 'apps': {},
                'inference': {'url': 'http://127.0.0.1:8008', 'models': ['kev', 'planner']}}

    async def test_waits_for_both_workers_before_speech_readiness(self):
        client = Inference(self.config())
        await client.http.aclose()
        polls = []
        def respond(request):
            if request.url.path == '/models':
                polls.append(True)
                return httpx.Response(200, json={'data': [
                    {'id': 'kev', 'status': {'value': 'loaded'}},
                    {'id': 'planner', 'status': {'value': 'loading' if len(polls) == 1 else 'loaded'}}]})
            self.assertEqual(len(polls), 2)
            return httpx.Response(200, json={'data': [{'id': 'planner'}]} if request.url.path == '/v1/models' else {'ready': True})
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        from unittest.mock import AsyncMock
        try:
            with patch('aurora_assistant.inference.asyncio.sleep', new_callable=AsyncMock):
                await client.wait_ready()
        finally:
            await client.close()

    async def test_worker_failure_is_not_reported_as_ready(self):
        client = Inference(self.config())
        await client.http.aclose()
        def respond(request):
            return httpx.Response(200, json={'data': [
                {'id': 'kev', 'status': {'value': 'unloaded', 'failed': True}},
                {'id': 'planner', 'status': {'value': 'loaded'}}]})
        client.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        try:
            with self.assertRaisesRegex(ValueError, 'failed to load'):
                await client.wait_ready()
        finally:
            await client.close()
