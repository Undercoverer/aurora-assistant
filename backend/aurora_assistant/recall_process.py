"""Bounded subprocess ownership for optional CPU recall."""
import asyncio
import json
import sys
from pathlib import Path


class RecallProcess:
    def __init__(self, config):
        self.config = config
        self.process = None
        self.lock = asyncio.Lock()
        self.failed = False

    async def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            async with asyncio.timeout(2):
                await process.wait()
        except TimeoutError:
            process.kill()
            async with asyncio.timeout(2):
                await process.wait()

    async def _exchange(self, request):
        encoded = json.dumps(request, ensure_ascii=False, allow_nan=False).encode() + b'\n'
        if len(encoded) > 1048576:
            raise ValueError('Recall input exceeds limit')
        self.process.stdin.write(encoded)
        await self.process.stdin.drain()
        line = await self.process.stdout.readline()
        if not line or len(line) > 65536:
            raise ValueError('Recall worker unavailable or reply oversized')
        response = json.loads(line)
        if type(response) is not dict or response.get('error'):
            raise ValueError('Local recall model failed')
        return response

    async def initialize(self):
        if self.failed:
            raise ValueError('Recall worker stopped; restart the controller')
        if self.process is not None:
            return
        directory = Path(self.config['directory'])
        for name in ('model.onnx', 'tokenizer.json'):
            if not directory.is_absolute() or not (directory / name).is_file():
                raise ValueError(f'Missing local retrieval asset: {name}')
        try:
            async with asyncio.timeout(30):
                self.process = await asyncio.create_subprocess_exec(
                    sys.executable, '-m', 'aurora_assistant.recall_worker',
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, limit=65536)
                result = await self._exchange({'config': self.config})
                if result != {'ready': True}:
                    raise ValueError('Invalid recall startup reply')
        except BaseException:
            self.failed = True
            await self.close()
            raise

    async def search(self, query, documents, limit=12):
        async with self.lock:
            await self.initialize()
            documents = list(documents)[:256]
            try:
                async with asyncio.timeout(self.config.get('timeoutSeconds', 5)):
                    response = await self._exchange({'query': query[:8192], 'documents': documents, 'limit': limit})
                indices = response.get('indices')
                if (type(indices) is not list or len(indices) > limit or len(set(indices)) != len(indices)
                        or any(type(i) is not int or not 0 <= i < len(documents) for i in indices)):
                    raise ValueError('Invalid recall selection')
                return [documents[i] for i in indices]
            except BaseException:
                self.failed = True
                await self.close()
                raise
