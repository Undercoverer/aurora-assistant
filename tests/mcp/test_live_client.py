"""Exact consent through Aurora -> stdio MCP -> isolated D-Bus fixture."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock
from dbus_fast.aio import MessageBus
from test_live_substrate import Fixture
from aurora_assistant.actions import Action
from aurora_assistant.mcp_client import Consent, MCPTransport, MCPFailure
from aurora_assistant.mcp_bus import MCPBusAccess


@unittest.skipUnless(os.environ.get('AURORA_MCP_TEST_BUS') == '1', 'Needs isolated test bus')
class LiveClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_approved_call_property_and_stale_owner(self):
        service = await MessageBus().connect()
        fixture = Fixture()
        service.export('/Fixture', fixture)
        await service.request_name('org.kde.AuroraMcpFixture')
        try:
            with tempfile.TemporaryDirectory() as directory:
                script = Path(directory) / 'server'
                source = Path(__file__).resolve().parents[2] / 'mcp'
                script.write_text(f'#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(source)!r})\nfrom aurora_mcdbus import main\nmain()\n')
                script.chmod(0o700)
                second = AsyncMock(return_value=False)
                consent = Consent(second)
                transport = MCPTransport(str(script), consent)
                async with transport.connect():
                    bus = MCPBusAccess({}, transport, consent)
                    endpoint = {'bus': 'session', 'destination': 'org.kde.AuroraMcpFixture',
                                'path': '/Fixture', 'interface': 'org.kde.AuroraMcpFixture'}
                    names = await bus.read(Action('dbus_list', 'session'))
                    self.assertIn(endpoint['destination'], names)
                    inspected = await bus.read(Action('dbus_inspect', {
                        k: v for k, v in endpoint.items() if k != 'interface'}))
                    self.assertTrue(inspected['interfaces'])
                    self.assertFalse(await bus.read(Action('dbus_get', {**endpoint, 'property': 'Enabled'})))
                    call = await bus.prepare(Action('dbus_call', {**endpoint, 'method': 'SetLevel', 'argumentsJson': '[50]'}))
                    consent.authorize([call])
                    self.assertIn('not independently verified', await bus.execute(call))
                    self.assertEqual(fixture.calls, [50])
                    prop = await bus.prepare(Action('dbus_set', {**endpoint, 'property': 'Enabled', 'valueJson': 'true'}))
                    consent.authorize([prop])
                    self.assertIn('true', await bus.execute(prop))
                    self.assertTrue(fixture.enabled)
                    stale = await bus.prepare(Action('dbus_call', {**endpoint, 'method': 'SetLevel', 'argumentsJson': '[70]'}))
                    consent.authorize([stale])
                    await service.release_name('org.kde.AuroraMcpFixture')
                    with self.assertRaisesRegex(MCPFailure, '^mcp.refused$'):
                        await bus.execute(stale)
                    self.assertEqual(fixture.calls, [50])
                    second.assert_not_awaited()
        finally:
            service.disconnect()
            await service.wait_for_disconnect()
