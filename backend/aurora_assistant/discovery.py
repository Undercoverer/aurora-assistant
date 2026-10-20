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


async def maintain(inference, bus, discover_native=True):
    cursor = DiscoveryCursor()
    while True:
        await inference.refresh_capabilities()
        if discover_native:
            try:
                async with asyncio.timeout(6):
                    await scan(inference.catalog, bus, cursor=cursor)
            except TimeoutError:
                event('capabilities.scan_budget_exhausted')
        await asyncio.sleep(240)
