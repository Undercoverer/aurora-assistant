"""Optional offline ONNX recall. Results only supplement planner evidence.

No action, policy decision, approval or Kev option is selected here.
"""
import hashlib
import json
from pathlib import Path
import threading
import numpy as np
from .catalog import words


def document_text(document):
    return json.dumps(document, sort_keys=True, ensure_ascii=False)[:4096]


def document_id(document):
    return hashlib.sha256(document_text(document).encode()).hexdigest()


class OnnxEncoder:
    def __init__(self, config):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        directory = Path(config['directory'])
        for name in ('model.onnx', 'tokenizer.json'):
            if not directory.is_absolute() or not (directory / name).is_file():
                raise ValueError(f'Missing local retrieval asset: {name}')
        self.tokenizer = Tokenizer.from_file(str(directory / 'tokenizer.json'))
        padding = self.tokenizer.padding
        if padding is None:
            vocab = self.tokenizer.get_vocab()
            pad = next((p for p in ('[PAD]', '<pad>') if p in vocab), None)
            if pad is None:
                raise ValueError('Retrieval tokenizer has no supported padding token')
            self.tokenizer.enable_padding(pad_id=vocab[pad], pad_token=pad)
        self.tokenizer.enable_truncation(max_length=config.get('maxTokens', 256))
        options = ort.SessionOptions()
        options.intra_op_num_threads = config.get('threads', 1)
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(directory / 'model.onnx'),
            sess_options=options, providers=['CPUExecutionProvider'])
        self.inputs = {item.name for item in self.session.get_inputs()}
        if not self.inputs or not self.inputs <= {'input_ids', 'attention_mask', 'token_type_ids'}:
            raise ValueError('Retrieval ONNX model must accept BERT-style token inputs')
        self.pooling = config.get('pooling', 'mean')

    def encode(self, texts):
        encoded = self.tokenizer.encode_batch(texts)
        inputs = {'input_ids': np.array([e.ids for e in encoded], dtype=np.int64),
                  'attention_mask': np.array([e.attention_mask for e in encoded], dtype=np.int64),
                  'token_type_ids': np.array([e.type_ids for e in encoded], dtype=np.int64)}
        output = np.asarray(self.session.run(None, {k: inputs[k] for k in self.inputs})[0])
        if output.ndim == 3:
            if self.pooling == 'cls':
                output = output[:, 0, :]
            else:
                mask = inputs['attention_mask'][..., None]
                output = (output * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1)
        if output.ndim != 2 or output.shape[0] != len(texts) or not np.isfinite(output).all():
            raise ValueError('Retrieval model returned invalid embeddings')
        norms = np.linalg.norm(output, axis=1, keepdims=True)
        if np.any(norms <= 0):
            raise ValueError('Retrieval model returned zero embeddings')
        return output / norms


class HybridRecall:
    def __init__(self, config, encoder=None):
        self.config = config
        self.encoder = encoder
        self.cache = {}
        self.lock = threading.Lock()

    def initialize(self):
        if self.encoder is None:
            self.encoder = OnnxEncoder(self.config)
            # Validate the actual configured graph before voice operation.
            self.encoder.encode(['Aurora capability'])

    def search(self, query, documents, limit=12, cancelled=None):
        with self.lock:
            self.initialize()
            documents = list(documents)[:256]
            if not documents:
                return []
            terms = words(query)
            lexical = sorted(range(len(documents)),
                key=lambda i: (-len(terms & words(document_text(documents[i]))), i))
            # Always preserve half of the lexical shortlist, including exact
            # names. Semantic recall cannot silently replace lexical matching.
            keep = min(len(documents), max(1, limit // 2))
            selected = lexical[:keep]
            bound = min(self.config.get('maxDocuments', 64), len(documents))
            pool = lexical[:bound]
            keys = {i: document_id(documents[i]) for i in pool}
            self.cache = {k: v for k, v in self.cache.items() if k in keys.values()}
            missing = [i for i in pool if keys[i] not in self.cache]
            for start in range(0, len(missing), 8):
                if cancelled is not None and cancelled.is_set():
                    return []
                batch = missing[start:start + 8]
                vectors = self.encoder.encode([document_text(documents[i]) for i in batch])
                self.cache.update((keys[i], vector) for i, vector in zip(batch, vectors))
            if cancelled is not None and cancelled.is_set():
                return []
            vector = self.encoder.encode([self.config.get('queryPrefix', '') + query[:8192]])[0]
            semantic = sorted(pool, key=lambda i: (-float(np.dot(self.cache[keys[i]], vector)), i))
            for index in semantic + lexical:
                if index not in selected:
                    selected.append(index)
                if len(selected) >= limit:
                    break
            return [documents[i] for i in selected[:limit]]
