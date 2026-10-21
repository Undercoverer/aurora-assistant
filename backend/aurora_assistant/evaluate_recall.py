"""Evaluate recall on explicit labeled cases; never invoke desktop actions."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import statistics
import time
from .catalog import words
from .recall import HybridRecall, document_id, document_text


def evaluate(documents, cases, recall=None, limit=12, repeats=3):
    if (not 1 <= limit <= 32 or not 1 <= repeats <= 20 or len(documents) > 256
            or not 1 <= len(cases) <= 1000):
        raise ValueError('Evaluation bounds exceeded')
    known = {document_id(d) for d in documents}
    for case in cases:
        if (type(case) is not dict or type(case.get('query')) is not str or len(case['query']) > 8192
                or type(case.get('expected')) is not list or not set(case['expected']) <= known):
            raise ValueError('Each case needs a bounded query and expected document IDs from the corpus')
    rows = {}
    for name in (['lexical', 'hybrid'] if recall is not None else ['lexical']):
        times, hits, positives, negatives, negative_candidates = [], 0, 0, 0, 0
        first_ms = None
        for _ in range(repeats):
            for case in cases:
                start = time.perf_counter()
                if name == 'hybrid':
                    selected = recall.search(case['query'], documents, limit)
                else:
                    terms = words(case['query'])
                    selected = sorted(documents, key=lambda d: -len(terms & words(document_text(d))))[:limit]
                elapsed = (time.perf_counter() - start) * 1000
                if first_ms is None:
                    first_ms = elapsed
                times.append(elapsed)
                predicted = {document_id(d) for d in selected}
                expected = set(case['expected'])
                if expected:
                    hits += len(expected & predicted) / len(expected)
                    positives += 1
                else:
                    negatives += 1
                    negative_candidates += bool(predicted)
        ordered = sorted(times)
        rows[name] = {
            'samples': len(times), 'positive_samples': positives, 'negative_samples': negatives,
            'recall_at_k': hits / positives if positives else None,
            'negative_with_candidates': negative_candidates / negatives if negatives else None,
            'first_request_ms': first_ms, 'p50_ms': statistics.median(times),
            'p95_ms': ordered[min(len(ordered)-1, int(.95 * len(ordered)))],
        }
    return {'k': limit, 'repeats': repeats, 'results': rows,
            'scope': 'Recall only; candidates are untrusted hints, not action selection or calibrated abstention.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--cases', required=True)
    parser.add_argument('--model-config', help='Retrieval configuration JSON with local model directory')
    parser.add_argument('--k', type=int, default=12)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    def load(path):
        value = Path(path).read_bytes()
        if len(value) > 1048576:
            raise ValueError('Evaluation input exceeds one MiB')
        return json.loads(value), hashlib.sha256(value).hexdigest()
    corpus, corpus_hash = load(args.catalog)
    cases, cases_hash = load(args.cases)
    config = None
    recall = None
    model_hash = None
    if args.model_config:
        config, _ = load(args.model_config)
        recall = HybridRecall(config)
        with (Path(config['directory']) / 'model.onnx').open('rb') as stream:
            model_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    result = evaluate(corpus['documents'], cases, recall, args.k, args.repeats)
    result.update(machine=platform.machine(), processor=platform.processor(),
                  python=platform.python_version(), corpus_sha256=corpus_hash,
                  cases_sha256=cases_hash, model_sha256=model_hash,
                  model=config.get('model') if config else None,
                  threads=config.get('threads', 1) if config else None)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
