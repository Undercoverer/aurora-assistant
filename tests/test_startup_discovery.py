import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from aurora_assistant.catalog import CapabilityCatalog
from aurora_assistant.discovery import compare_snapshot, maintain

ACTION = SimpleNamespace(name='dbus_inspect', argument={'bus': 'session', 'destination': 'org.kde.Test', 'path': '/'})
VALUE = {'owner': ':1.2', 'children': [], 'interfaces': [{'name': 'org.kde.Test',
         'methods': [{'name': 'Pause', 'input': '', 'output': ''}], 'properties': []}]}


class StartupDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_runs_once_and_is_bounded(self):
        catalog = CapabilityCatalog(max_age=None)
        inference = SimpleNamespace(config={'settings': {'discoveryMode': 'startup', 'scanMaxObjects': 2}}, catalog=catalog,
                                    refresh_capabilities=AsyncMock())
        bus = SimpleNamespace(read=AsyncMock())
        async def read(action):
            if action.name == 'dbus_list':
                return ['org.kde.A', 'org.kde.B', 'org.kde.C'] if action.argument == 'session' else []
            return VALUE
        bus.read.side_effect = read
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'XDG_CACHE_HOME': directory}):
            await maintain(inference, bus)
        self.assertEqual(sum(c.args[0].name == 'dbus_inspect' for c in bus.read.call_args_list), 2)
        inference.refresh_capabilities.assert_awaited_once()

    async def test_snapshot_is_nonexecutable_hashes_and_detects_change(self):
        catalog = CapabilityCatalog(max_age=None)
        catalog.observe(ACTION, VALUE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fingerprints.json'
            self.assertFalse(compare_snapshot(catalog, path)['previous_snapshot'])
            self.assertEqual(compare_snapshot(catalog, path)['added'], 0)
            raw = path.read_text()
            self.assertNotIn('org.kde', raw)
            changed = json.loads(json.dumps(VALUE))
            changed['interfaces'][0]['methods'][0]['output'] = 's'
            catalog.observe(ACTION, changed)
            self.assertEqual(compare_snapshot(catalog, path)['changed'], 1)
            catalog.objects.clear()
            self.assertEqual(compare_snapshot(catalog, path)['removed'], 1)

    async def test_startup_hints_survive_ttl_but_periodic_expire(self):
        startup, periodic = CapabilityCatalog(max_age=None), CapabilityCatalog()
        with patch('aurora_assistant.catalog.time.monotonic', return_value=1):
            startup.observe(ACTION, VALUE)
            periodic.observe(ACTION, VALUE)
        with patch('aurora_assistant.catalog.time.monotonic', return_value=900):
            self.assertTrue(startup.documents())
            self.assertEqual(periodic.documents(), [])

    async def test_realtime_drops_stale_objects_and_reintrospects_each_turn(self):
        from aurora_assistant.discovery import refresh_live
        catalog = CapabilityCatalog()
        catalog.observe(ACTION, VALUE)
        inference = SimpleNamespace(config={'settings': {'scanMaxObjects': 2}}, catalog=catalog,
                                    refresh_capabilities=AsyncMock())
        bus = SimpleNamespace(read=AsyncMock())
        bus.read.side_effect = lambda action: [] if action.name == 'dbus_list' else VALUE
        await refresh_live(inference, bus)
        self.assertEqual(catalog.documents(), [])
        self.assertEqual(bus.read.await_count, 2)
        async def read(action):
            if action.name == 'dbus_list':
                return ['org.kde.New'] if action.argument == 'session' else []
            return VALUE
        bus.read.side_effect = read
        await refresh_live(inference, bus)
        self.assertEqual(catalog.documents()[0]['target']['destination'], 'org.kde.New')
        self.assertEqual(catalog.documents()[0]['candidate']['name'], 'dbus_inspect')
        self.assertFalse(any(call.args[0].name == 'dbus_inspect' for call in bus.read.call_args_list))
        self.assertEqual(inference.refresh_capabilities.await_count, 2)

    async def test_live_refresh_finishes_before_planning(self):
        from aurora_assistant.agent import SettingsAgent
        order = []
        async def refresh():
            order.append('refresh')
        async def plan(*args, **kwargs):
            order.append('plan')
            return {'actions': [], 'reply': 'Ready'}
        inference = SimpleNamespace(plan=plan)
        agent = SettingsAgent({'apps': {}}, inference, None, None, None, live_refresh=refresh)
        self.assertEqual(await agent.run('hello'), 'Ready')
        self.assertEqual(order, ['refresh', 'plan'])

    async def test_realtime_startup_does_not_scan_or_write_fingerprints(self):
        inference = SimpleNamespace(config={'settings': {'discoveryMode': 'realtime'}},
                                    catalog=CapabilityCatalog(), refresh_capabilities=AsyncMock())
        bus = SimpleNamespace(read=AsyncMock())
        with patch('aurora_assistant.discovery.compare_snapshot') as compare:
            await maintain(inference, bus)
        bus.read.assert_not_awaited()
        compare.assert_not_called()

    async def test_empty_root_exposes_child_inspection_without_guessing(self):
        catalog = CapabilityCatalog()
        catalog.observe(ACTION, {'interfaces': [], 'children': ['Device', '../invalid']})
        docs = catalog.documents()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]['candidate'], {'name': 'dbus_inspect',
            'argument': {**ACTION.argument, 'path': '/Device'}})
