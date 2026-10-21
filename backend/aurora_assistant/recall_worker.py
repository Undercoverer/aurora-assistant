"""Private offline inference worker. Protocol errors contain no input text."""
import json
import sys
from .recall import HybridRecall


def read():
    line = sys.stdin.buffer.readline(1048577)
    if not line:
        return None
    if len(line) > 1048576:
        raise ValueError('Input exceeds limit')
    return json.loads(line)


def write(value):
    print(json.dumps(value, allow_nan=False), flush=True)


def main():
    try:
        initial = read()
        recall = HybridRecall(initial['config'])
        recall.initialize()
        write({'ready': True})
        while (request := read()) is not None:
            documents = request['documents']
            if len(documents) > 256 or not 1 <= request['limit'] <= 32:
                raise ValueError('Invalid bounds')
            selected = recall.search(request['query'], documents, request['limit'])
            # Object identity preserves exact original records, including duplicates.
            indices = {id(doc): i for i, doc in enumerate(documents)}
            write({'indices': [indices[id(doc)] for doc in selected]})
    except Exception:
        write({'error': 'recall_failed'})


if __name__ == '__main__':
    main()
