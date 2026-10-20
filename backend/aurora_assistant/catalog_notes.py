"""Persistent, unverified explanations. Never a source of executable capabilities."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from .telemetry import failure

MAX_BYTES = 1048576
MAX_ENTRIES = 512
MAX_AGE = 7 * 86400


def fingerprint(document):
    observed = {key: document[key] for key in ('target', 'kind', 'name', 'detail')}
    observed['target'] = {k: v for k, v in observed['target'].items() if k != 'owner'}
    return hashlib.sha256(json.dumps(observed, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def valid_note(note):
    return (type(note) is dict and set(note) == {'summary', 'unknowns'}
            and all(type(v) is str and len(v) <= 600 for v in note.values())
            and bool(note['summary'].strip()))


class CatalogNotes:
    def __init__(self, model, path=None):
        self.model, self.path, self.entries = model, path, {}
        if path is not None:
            try:
                self.load()
            except (OSError, ValueError, TypeError):
                # A corrupt cache must not prevent the voice assistant starting.
                self.entries = {}

    def get(self, document):
        entry = self.entries.get(fingerprint(document))
        if (not entry or entry['model'] != self.model
                or not 0 <= time.time() - entry['created'] <= MAX_AGE):
            return None
        return {'provenance': 'model_inferred_unverified', **entry['note']}

    def put(self, document, note):
        if not valid_note(note):
            raise ValueError('Invalid catalog explanation')
        key = fingerprint(document)
        self.entries.pop(key, None)
        self.entries[key] = {'model': self.model, 'created': time.time(), 'note': dict(note)}
        while len(self.entries) > MAX_ENTRIES:
            self.entries.pop(next(iter(self.entries)))
        if self.path is not None:
            try:
                self.save()
            except OSError as exc:
                failure('catalog.save_failed', exc)

    def load(self):
        parent = Path(self.path).parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid():
            raise ValueError('Invalid catalog cache directory')
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > MAX_BYTES:
                raise ValueError('Invalid catalog cache file')
            data = json.loads(stream.read(MAX_BYTES + 1))
        if type(data) is not dict or type(data.get('version')) is not int or data.get('version') != 1 or type(data.get('entries')) is not dict:
            raise ValueError('Invalid catalog cache format')
        entries = data['entries']
        if len(entries) > MAX_ENTRIES:
            raise ValueError('Catalog cache is too large')
        for key, entry in entries.items():
            if (type(key) is not str or len(key) != 64 or any(c not in '0123456789abcdef' for c in key)
                    or type(entry) is not dict or set(entry) != {'model', 'created', 'note'}
                    or type(entry['model']) is not str or len(entry['model']) > 512
                    or type(entry['created']) not in (int, float) or not valid_note(entry['note'])):
                raise ValueError('Invalid catalog cache entry')
        self.entries = entries

    def save(self):
        path = Path(self.path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise OSError('Catalog directory must belong to the desktop user')
        path.parent.chmod(0o700)
        encoded = json.dumps({'version': 1, 'entries': self.entries}).encode()
        # JSON escaping may enlarge model descriptions; evict oldest entries.
        while len(encoded) > MAX_BYTES and self.entries:
            self.entries.pop(next(iter(self.entries)))
            encoded = json.dumps({'version': 1, 'entries': self.entries}).encode()
        fd, temporary = tempfile.mkstemp(prefix='.notes-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
