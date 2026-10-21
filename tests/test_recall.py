import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from aurora_assistant.recall import HybridRecall, OnnxEncoder, document_id
from aurora_assistant.evaluate_recall import evaluate
from aurora_assistant.recall_process import RecallProcess


class Encoder:
    def __init__(self):
        self.batches = []
    def encode(self, texts):
        self.batches.append(texts)
        return np.array([[1., 0.] if 'semantic_target' in t or t == 'query' else [0., 1.] for t in texts])


class RecallTests(unittest.TestCase):
    def test_semantic_recall_preserves_lexical_half_and_exact_records(self):
        encoder = Encoder()
        recall = HybridRecall({'maxDocuments': 16}, encoder)
        docs = [{'name': f'query {n}'} for n in range(6)] + [{'name': 'semantic_target'}]
        selected = recall.search('query', docs, limit=4)
        self.assertIs(selected[0], docs[0])
        self.assertIs(selected[1], docs[1])
        self.assertIn(docs[-1], selected)
        self.assertTrue(all(any(d is original for original in docs) for d in selected))

    def test_cache_invalidates_changed_document_and_is_bounded(self):
        encoder = Encoder()
        recall = HybridRecall({'maxDocuments': 2}, encoder)
        docs = [{'name': str(n)} for n in range(20)]
        recall.search('query', docs)
        self.assertEqual(len(recall.cache), 2)
        encoder.batches.clear()
        recall.search('query', docs)
        self.assertEqual(encoder.batches, [['query']])
        docs[0]['name'] = 'changed'
        encoder.batches.clear()
        recall.search('query', docs)
        self.assertEqual(len(encoder.batches), 2)

    def test_evaluation_reports_negatives_and_sample_count(self):
        docs = [{'name': 'volume'}, {'name': 'theme'}]
        cases = [{'query': 'volume', 'expected': [document_id(docs[0])]},
                 {'query': 'unrelated', 'expected': []}]
        result = evaluate(docs, cases, limit=1, repeats=2)['results']['lexical']
        self.assertEqual(result['recall_at_k'], 1)
        self.assertEqual(result['samples'], 4)
        self.assertEqual(result['negative_with_candidates'], 1)
        with self.assertRaises(ValueError):
            evaluate(docs, [{'query': 'x', 'expected': ['unknown']}])

    def test_cancelled_batch_stops_before_encoding(self):
        import threading
        cancelled = threading.Event()
        cancelled.set()
        encoder = Encoder()
        self.assertEqual(HybridRecall({}, encoder).search('query', [{'name': 'x'}], cancelled=cancelled), [])
        self.assertEqual(encoder.batches, [])


def assets(directory):
    """Small synthetic graph: verifies runtime plumbing, not model accuracy."""
    import onnx
    from onnx import TensorProto, helper
    from tokenizers import Tokenizer, models, pre_tokenizers
    tokenizer = Tokenizer(models.WordLevel({'[PAD]': 0, '[UNK]': 1, 'Aurora': 2, 'capability': 3}, unk_token='[UNK]'))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.save(str(directory / 'tokenizer.json'))
    graph = helper.make_graph([
        helper.make_node('Cast', ['input_ids'], ['floats'], to=TensorProto.FLOAT),
        helper.make_node('Unsqueeze', ['floats', 'axes'], ['expanded']),
        helper.make_node('Concat', ['expanded', 'expanded'], ['vectors'], axis=2),
    ], 'test', [helper.make_tensor_value_info('input_ids', TensorProto.INT64, ['batch', 'sequence'])],
       [helper.make_tensor_value_info('vectors', TensorProto.FLOAT, ['batch', 'sequence', 2])],
       [helper.make_tensor('axes', TensorProto.INT64, [1], [2])])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 13)], ir_version=8)
    onnx.save(model, str(directory / 'model.onnx'))


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_offline_graph_and_process_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            assets(directory)
            config = {'directory': str(directory), 'model': 'synthetic-test-only', 'maxTokens': 16}
            encoder = OnnxEncoder(config)
            self.assertEqual(encoder.encode(['Aurora capability', 'Aurora']).shape, (2, 2))
            worker = RecallProcess(config)
            try:
                await worker.initialize()
                process = worker.process
                docs = [{'name': 'Aurora capability'}, {'name': 'unknown'}]
                self.assertEqual(await worker.search('Aurora', docs, limit=1), docs[:1])
            finally:
                await worker.close()
            self.assertIsNotNone(process.returncode)

    async def test_missing_assets_fail_before_process_start(self):
        worker = RecallProcess({'directory': '/missing/aurora-retrieval'})
        with self.assertRaisesRegex(ValueError, 'Missing local retrieval asset'):
            await worker.initialize()
        self.assertIsNone(worker.process)

    async def test_request_cancellation_terminates_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            assets(directory)
            worker = RecallProcess({'directory': str(directory)})
            await worker.initialize()
            process = worker.process
            entered = asyncio.Event()
            async def stall(request):
                entered.set()
                await asyncio.Event().wait()
            with patch.object(worker, '_exchange', side_effect=stall):
                task = asyncio.create_task(worker.search('x', [{'name': 'x'}]))
                await entered.wait()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertIsNone(worker.process)
            self.assertIsNotNone(process.returncode)
            self.assertTrue(worker.failed)

class ProvisioningTests(unittest.TestCase):
    def test_named_files_use_one_resolved_commit_and_validate_locally(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from aurora_assistant.models import install_retrieval
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph, tokenizer = root / 'graph', root / 'tokenizer'
            graph.write_bytes(b'test graph')
            tokenizer.write_text('{}')
            stage = root / 'stage'
            stage.mkdir()
            api = Mock()
            api.model_info.return_value = SimpleNamespace(sha='resolved-commit')
            spec = {'repo': 'owner/model', 'revision': 'chosen-ref',
                    'onnxFile': 'onnx/encoder.onnx', 'tokenizerFile': 'tokenizer.json'}
            with patch('huggingface_hub.HfApi', return_value=api), \
                 patch('huggingface_hub.hf_hub_download', side_effect=[str(graph), str(tokenizer)]) as download, \
                 patch('aurora_assistant.recall.OnnxEncoder') as encoder:
                result = install_retrieval(spec, stage)
            self.assertEqual(result['revision'], 'resolved-commit')
            self.assertTrue(all(c.kwargs['revision'] == 'resolved-commit' for c in download.call_args_list))
            encoder.return_value.encode.assert_called_once()
            self.assertEqual((stage / 'retrieval/model.onnx').read_bytes(), b'test graph')

class StartupFeedbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_startup_error_is_visible_and_resources_close(self):
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock, Mock
        from aurora_assistant import main
        config = {'apps': {}, 'commands': {}, 'presentation': {'errorSeconds': 0},
                  'execution': {'backend': 'mcp', 'executable': '/missing/server'}}
        inference, overlay, approval = AsyncMock(), AsyncMock(), AsyncMock()
        overlay.close = Mock()
        @asynccontextmanager
        async def unavailable(self):
            raise RuntimeError('Unavailable test server')
            yield
        with patch.object(main, 'Inference', return_value=inference), \
             patch.object(main, 'Overlay', return_value=overlay), \
             patch.object(main, 'Approval', return_value=approval), \
             patch('aurora_assistant.mcp_client.MCPTransport.connect', unavailable):
            with self.assertRaisesRegex(RuntimeError, 'Unavailable test server'):
                await main.run(config, text='test')
        self.assertIn(('error',), [call.args for call in overlay.state.call_args_list])
        self.assertTrue(any('Assistant service failed' in call.args[0] for call in overlay.message.call_args_list))
        inference.close.assert_awaited_once()
        approval.close.assert_awaited_once()
        overlay.close.assert_called_once()
