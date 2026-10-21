"""Generic request discovery uses current observations, not application categories."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from aurora_assistant.actions import Action
from aurora_assistant.agent import SettingsAgent
from aurora_assistant.catalog import CapabilityCatalog
from aurora_assistant.discovery import refresh_live
from aurora_assistant.mcp_bus import MCPBusAccess
from aurora_assistant.mcp_client import Consent


class RequestDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unfamiliar_service_is_discovered_and_children_followed(self):
        catalog = CapabilityCatalog()
        config = {'apps': {}, 'settings': {'enable': True}}
        reads = []
        async def read(action):
            reads.append(action)
            if action.name == 'dbus_list':
                return {'services': ['org.vendor.Instrument'] if action.argument == 'session' else [], 'truncated': False}
            if action.argument['path'] == '/':
                return {'interfaces': [], 'children': ['Probe'], 'owner': ':1.20'}
            return {'interfaces': [{'name': 'org.vendor.Sensor', 'methods': [],
                    'properties': [{'name': 'Reading', 'signature': 'd', 'access': 'read'}]}], 'children': [], 'owner': ':1.20'}
        bus = SimpleNamespace(read=read)
        rounds = 0
        async def plan(text, evidence):
            nonlocal rounds
            rounds += 1
            if rounds == 1:
                self.assertEqual(evidence[0]['result']['services'], ['org.vendor.Instrument'])
                candidate = next(d['candidate'] for d in catalog.documents() if d['kind'] == 'service')
            elif rounds == 2:
                candidate = next(d['candidate'] for d in catalog.documents() if d['kind'] == 'object')
                self.assertEqual(candidate['argument']['path'], '/Probe')
            else:
                self.assertTrue(any(d['name'] == 'Reading' for d in catalog.documents()))
                return {'actions': [], 'reply': 'The interface exposes a reading.'}
            return {'actions': [candidate], 'reply': ''}
        inference = SimpleNamespace(config=config, catalog=catalog, plan=plan, refresh_capabilities=AsyncMock())
        desktop = SimpleNamespace(bus=bus, read=read, prepare=AsyncMock(), execute=AsyncMock())
        agent = SettingsAgent(config, inference, desktop, None, None,
                              live_refresh=lambda: refresh_live(inference, bus))
        await agent.run('Show the available measurement controls')
        self.assertEqual([a.argument['path'] for a in reads if a.name == 'dbus_inspect'], ['/', '/Probe'])
        desktop.prepare.assert_not_awaited()
        desktop.execute.assert_not_awaited()
        # The next request cannot retain an instrument that left the bus.
        bus.read = AsyncMock(return_value={'services': [], 'truncated': False})
        await refresh_live(inference, bus)
        self.assertEqual(catalog.documents(), [])

    async def test_all_scope_and_truncated_results_are_explicit(self):
        transport = SimpleNamespace(call=AsyncMock(return_value={
            'services': ['org.vendor.Device'], 'truncated': True}))
        bus = MCPBusAccess({}, transport, Consent(None))
        result = await bus.read(Action('dbus_list', 'session'))
        self.assertEqual(result['services'], ['org.vendor.Device'])
        self.assertTrue(result['truncated'])
        restricted = MCPBusAccess({'discoveryScope': 'restricted'}, transport, Consent(None))
        self.assertEqual((await restricted.read(Action('dbus_list', 'session')))['services'], [])

    async def test_listing_failure_does_not_mean_absence(self):
        catalog = CapabilityCatalog()
        inference = SimpleNamespace(config={}, catalog=catalog, refresh_capabilities=AsyncMock())
        bus = SimpleNamespace(read=AsyncMock(side_effect=RuntimeError('private failure')))
        result = await refresh_live(inference, bus)
        self.assertEqual(len(result), 2)
        self.assertIn('availability is unknown', result[0]['error'])
        self.assertNotIn('private failure', str(result))
