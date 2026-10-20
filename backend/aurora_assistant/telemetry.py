"""Structured local events. Content is opt-in; audio is never recorded."""
from contextlib import contextmanager
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
from time import monotonic
import traceback
import uuid
from threading import Lock

turn_id = ContextVar('aurora_turn', default=None)
log = logging.getLogger('aurora')
log_content = False
_recent = deque(maxlen=128)
_recent_lock = Lock()


def configure(config=None):
    global log_content
    log_content = (config or {}).get('diagnostics', {}).get('logContent', False)
    logging.basicConfig(level=logging.WARNING, format='%(message)s')
    log.setLevel(logging.INFO)


def event(name, **fields):
    row = {'time': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
        'monotonic': round(monotonic(), 3), 'pid': os.getpid(),
        'turn': turn_id.get(), 'event': name, **fields}
    # Independent of journal capture and third-party logging configuration.
    # Keep only small metadata rows; never copy transcript content into this buffer.
    recent = {key: value for key, value in row.items() if key not in {'text', 'error_message'}}
    if len(json.dumps(recent).encode()) > 1536:
        recent = {key: row[key] for key in ('time', 'pid', 'turn', 'event')}
        recent['detail_omitted'] = True
    with _recent_lock:
        _recent.append(recent)
    log.info(json.dumps(row, ensure_ascii=False))


def snapshot():
    with _recent_lock:
        return {'pid': os.getpid(), 'events': list(_recent)}


def failure(name, exc, **fields):
    response = getattr(exc, 'response', None)
    status = getattr(response, 'status_code', None)
    # Only static validation reasons are safe without content logging. Arbitrary
    # exception messages can contain model output, URLs, or private D-Bus values.
    from .actions import PlanValidationError
    if isinstance(exc, PlanValidationError):
        fields['validation_reason'] = str(exc)[:256]
    if log_content:
        fields['error_message'] = str(exc)[:1000]
    event(name, error_type=type(exc).__name__,
          frames=[f'{os.path.basename(f.filename)}:{f.lineno}:{f.name}'
                  for f in traceback.extract_tb(exc.__traceback__)[-8:]],
          **({'http_status': status} if type(status) is int else {}), **fields)


def content(name, text):
    event(name, characters=len(text), **({'text': text} if log_content else {}))


@contextmanager
def phase(name, **fields):
    start = monotonic()
    event(name + '.start', **fields)
    try:
        yield
    except BaseException as exc:
        failure(name + '.failed', exc, elapsed_ms=round((monotonic() - start) * 1000), **fields)
        raise
    else:
        event(name + '.done', elapsed_ms=round((monotonic() - start) * 1000), **fields)


def new_turn():
    return turn_id.set(uuid.uuid4().hex[:12])
