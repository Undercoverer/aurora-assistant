"""Bounded, read-only discovery of running D-Bus objects."""
import asyncio
from collections import deque
from .actions import Action
from .telemetry import event, failure


async def scan(catalog, bus, *, max_objects=24):
    """Browse live object trees; never activate services or guess method names."""
    queue = deque()
    for scope in ('session', 'system'):
        try:
            names = await bus.read(Action('dbus_list', scope))
            queue.extend((scope, name, '/') for name in names[:12])
        except Exception as exc:
            failure('capabilities.list_failed', exc, bus=scope)
    visited = set()
    while queue and len(visited) < max_objects:
        scope, destination, path = queue.popleft()
        key = (scope, destination, path)
        if key in visited:
            continue
        visited.add(key)
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
                        queue.append((scope, destination, nested))
        except Exception as exc:
            failure('capabilities.inspect_failed', exc)
    event('capabilities.scan_done', objects=len(visited))


async def maintain(inference, bus, discover_native=True):
    while True:
        await inference.refresh_capabilities()
        if discover_native:
            try:
                async with asyncio.timeout(6):
                    await scan(inference.catalog, bus)
            except TimeoutError:
                event('capabilities.scan_budget_exhausted')
        await asyncio.sleep(240)
