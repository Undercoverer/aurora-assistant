"""Bounded, read-only discovery of running D-Bus objects."""
import asyncio
from collections import deque
from .actions import Action
from .telemetry import event, failure


class DiscoveryCursor:
    def __init__(self):
        self.queue = deque()
        self.seen = set()


async def scan(catalog, bus, *, max_objects=24, cursor=None):
    """Continue a bounded live-object crawl across sweeps, never guessing paths."""
    cursor = cursor or DiscoveryCursor()
    if not cursor.queue:
        cursor.seen.clear()
        for scope in ('session', 'system'):
            try:
                names = await bus.read(Action('dbus_list', scope))
                cursor.queue.extend((scope, name, '/') for name in names[:150])
            except Exception as exc:
                failure('capabilities.list_failed', exc, bus=scope)
    attempts = 0
    while cursor.queue and attempts < max_objects:
        scope, destination, path = cursor.queue.popleft()
        key = (scope, destination, path)
        if key in cursor.seen:
            continue
        cursor.seen.add(key)
        attempts += 1
        action = Action('dbus_inspect', {'bus': scope, 'destination': destination, 'path': path})
        try:
            value = await bus.read(action)
            catalog.observe(action, value)
            for child in value.get('children', [])[:32]:
                if (type(child) is str and child and all(
                        part and all(c.isascii() and (c.isalnum() or c == '_') for c in part)
                        for part in child.split('/'))):
                    nested = path.rstrip('/') + '/' + child
                    if len(nested) <= 512:
                        item = (scope, destination, nested)
                        if item not in cursor.seen and item not in cursor.queue and len(cursor.queue) + len(cursor.seen) < 512:
                            cursor.queue.append(item)
        except Exception as exc:
            failure('capabilities.inspect_failed', exc)
    event('capabilities.scan_done', objects=attempts, queued=len(cursor.queue))


def compare_snapshot(catalog, path):
    """Persist hashes only; cached records are never executable capabilities."""
    import hashlib
    import json
    from pathlib import Path
    current = {}
    for doc in catalog.documents()[:256]:
        target = {k: v for k, v in doc['target'].items() if k != 'owner'}
        key = json.dumps([target, doc['kind'], doc['name'], doc.get('candidate')], sort_keys=True)
        identity = hashlib.sha256(key.encode()).hexdigest()
        content = json.dumps({'target': target, 'detail': doc['detail'],
                              'description': doc.get('description')}, sort_keys=True)
        current[identity] = hashlib.sha256(content.encode()).hexdigest()
    old = {}
    existed = False
    try:
        if path.exists() and path.stat().st_size <= 131072:
            value = json.loads(path.read_text())
            if (type(value) is dict and len(value) <= 256 and all(
                    type(k) is str and type(v) is str and len(k) == len(v) == 64
                    and all(c in '0123456789abcdef' for c in k + v) for k, v in value.items())):
                old, existed = value, True
    except (OSError, ValueError):
        pass
    result = {'previous_snapshot': existed, 'observed': len(current),
              'added': len(current.keys() - old.keys()),
              'removed': len(old.keys() - current.keys()),
              'changed': sum(current[k] != old[k] for k in current.keys() & old.keys())}
    catalog.comparison = result
    event('capabilities.startup_comparison', **result)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(current, sort_keys=True))
        temporary.chmod(0o600)
        temporary.replace(path)
    except OSError as exc:
        failure('capabilities.snapshot_write_failed', exc)
    return result


async def maintain(inference, bus, discover_native=True):
    import os
    from pathlib import Path
    settings = inference.config.get('settings', {})
    startup = settings.get('discoveryMode', 'startup') == 'startup'
    cursor = DiscoveryCursor()
    while True:
        await inference.refresh_capabilities()
        if discover_native:
            try:
                async with asyncio.timeout(settings.get('scanTimeoutSeconds', 6)):
                    await scan(inference.catalog, bus, cursor=cursor,
                               max_objects=settings.get('scanMaxObjects', 24))
            except TimeoutError:
                event('capabilities.scan_budget_exhausted')
        if startup:
            cache = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache')))
            compare_snapshot(inference.catalog, cache / 'aurora-assistant' / 'capability-fingerprints.json')
            return
        await asyncio.sleep(240)
