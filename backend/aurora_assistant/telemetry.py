"""Structured local events. Content is opt-in; audio is never recorded."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
from time import monotonic
import traceback
import uuid

turn_id = ContextVar('aurora_turn', default=None)
log = logging.getLogger('aurora')
log_content = False


def configure(config=None):
    global log_content
    log_content = (config or {}).get('diagnostics', {}).get('logContent', False)
    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    log.setLevel(logging.INFO)


def event(name, **fields):
    log.info(json.dumps({'time': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        'monotonic': round(monotonic(), 3), 'pid': os.getpid(),
        'turn': turn_id.get(), 'event': name, **fields}, ensure_ascii=False))


def content(name, text):
    event(name, characters=len(text), **({'text': text} if log_content else {}))


@contextmanager
def phase(name, **fields):
    start = monotonic()
    event(name + '.start', **fields)
    try:
        yield
    except BaseException as exc:
        event(name + '.failed', elapsed_ms=round((monotonic() - start) * 1000),
              error_type=type(exc).__name__,
              frames=[f'{f.filename}:{f.lineno}:{f.name}' for f in traceback.extract_tb(exc.__traceback__)], **fields)
        raise
    else:
        event(name + '.done', elapsed_ms=round((monotonic() - start) * 1000), **fields)


def new_turn():
    return turn_id.set(uuid.uuid4().hex[:12])
