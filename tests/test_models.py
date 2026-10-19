import copy
import json
from pathlib import Path
import tempfile
import unittest
from aurora_assistant.models import provision, check, spec_hash


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.spec = {'stt': 'tiny.en', 'llm': 'qwen3:4b'}
        self.installs = []

    def tearDown(self):
        self.temp.cleanup()

    def install(self, spec, path):
        self.installs.append(copy.deepcopy(spec))
        (path / 'model.onnx').write_bytes(b'fake-model-for-atomicity-tests')
        return {'test': 'revision'}

    def ollama(self, spec, refresh=False):
        return {spec['llm']: 'digest'}

    def test_success_creates_atomic_generation_and_manifest(self):
        provision(self.spec, self.root, installer=self.install, ollama=self.ollama)
        data = check(self.spec, self.root, full=True)
        self.assertEqual(data['spec_hash'], spec_hash(self.spec))
        self.assertIn('model.onnx', data['files'])
        self.assertTrue((self.root / 'current').is_symlink())

    def test_unchanged_configuration_does_not_download_again(self):
        for _ in range(2):
            provision(self.spec, self.root, installer=self.install, ollama=self.ollama)
        self.assertEqual(len(self.installs), 1)

    def test_failed_download_keeps_previous_generation(self):
        provision(self.spec, self.root, installer=self.install, ollama=self.ollama)
        previous = (self.root / 'current').resolve()
        changed = {**self.spec, 'stt': 'nonexistent-model'}
        def fail(spec, path):
            (path / 'partial.bin').write_bytes(b'partial')
            raise ValueError('Unknown model')
        with self.assertRaisesRegex(ValueError, 'Unknown model'):
            provision(changed, self.root, installer=fail, ollama=self.ollama)
        self.assertEqual(previous, (self.root / 'current').resolve())
        with self.assertRaisesRegex(ValueError, 'do not match'):
            check(changed, self.root)
        self.assertEqual(len(list((self.root / 'generations').iterdir())), 1)

    def test_corruption_is_detected_and_reprovisioned(self):
        provision(self.spec, self.root, installer=self.install, ollama=self.ollama)
        (self.root / 'current/model.onnx').write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            check(self.spec, self.root, full=True)
        provision(self.spec, self.root, installer=self.install, ollama=self.ollama)
        self.assertEqual(len(self.installs), 2)

    def test_missing_ollama_model_blocks_activation(self):
        def missing(spec, refresh=False):
            raise ValueError('Model not found')
        with self.assertRaisesRegex(ValueError, 'not found'):
            provision(self.spec, self.root, installer=self.install, ollama=missing)
        self.assertFalse((self.root / 'current').exists())
        self.assertFalse(self.installs)
