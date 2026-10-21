"""Exact consent through Aurora -> stdio MCP -> isolated D-Bus fixture."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method
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
                    self.assertIn(endpoint['destination'], names['services'])
                    inspected = await bus.read(Action('dbus_inspect', {
                        k: v for k, v in endpoint.items() if k != 'interface'}))
                    self.assertTrue(inspected['interfaces'])
                    self.assertFalse(await bus.read(Action('dbus_get', {**endpoint, 'property': 'Enabled'})))
                    call = await bus.prepare(Action('dbus_call', {**endpoint, 'method': 'SetLevel', 'argumentsJson': '[50]'}))
                    consent.authorize([call])
                    self.assertIn('not independently verified', await bus.execute(call))
                    self.assertEqual(fixture.calls, [50])
                    routine = await bus.prepare(Action('dbus_call', {**endpoint, 'method': 'SetLevel', 'argumentsJson': '[65]'}))
                    routine = consent.apply_policy(routine, 'ordinary')
                    consent.authorize_routine([routine])
                    await bus.execute(routine)
                    self.assertEqual(fixture.calls, [50, 65])
                    prop = await bus.prepare(Action('dbus_set', {**endpoint, 'property': 'Enabled', 'valueJson': 'true'}))
                    consent.authorize([prop])
                    self.assertIn('true', await bus.execute(prop))
                    self.assertTrue(fixture.enabled)
                    from types import SimpleNamespace
                    from aurora_assistant.agent import SettingsAgent
                    from aurora_assistant.approval import Approval
                    from aurora_assistant.mcp_desktop import MCPDesktop
                    approval = Approval()
                    agent = SettingsAgent({'apps': {}},
                        SimpleNamespace(assess_effects=AsyncMock(return_value=['destructive'])),
                        MCPDesktop(bus, None), approval,
                        SimpleNamespace(state=AsyncMock(), message=AsyncMock()), device_policy=True)
                    agent.voice_confirmation = True
                    try:
                        spoken = await bus.prepare(Action('dbus_call', {**endpoint, 'method': 'SetLevel', 'argumentsJson': '[68]'}))
                        self.assertIn('Proceed?', await agent._execute_plan('fixture destructive operation', [spoken]))
                        self.assertEqual(fixture.calls, [50, 65])
                        await agent.run('yes')
                        self.assertEqual(fixture.calls, [50, 65, 68])
                    finally:
                        agent.cancel_confirmation()
                        await approval.close()
                    stale = await bus.prepare(Action('dbus_call', {**endpoint, 'method': 'SetLevel', 'argumentsJson': '[70]'}))
                    consent.authorize([stale])
                    await service.release_name('org.kde.AuroraMcpFixture')
                    with self.assertRaisesRegex(MCPFailure, '^mcp.refused$'):
                        await bus.execute(stale)
                    self.assertEqual(fixture.calls, [50, 65, 68])
                    second.assert_not_awaited()
        finally:
            service.disconnect()
            await service.wait_for_disconnect()


class AdapterFixture(ServiceInterface):
    def __init__(self):
        super().__init__('org.aurora.Desktop1')
        self.applied = []
        self.tokens = {}

    @method()
    def Describe(self) -> 's':
        return '{"version":1,"actions":[]}'

    @method()
    def Read(self, topic: 's') -> 's':
        return '{"reply":"fixture read"}'

    @method()
    def Prepare(self, name: 's', argument: 's') -> 's':
        import json
        import time
        token = str(len(self.tokens))
        plan = {'action': {'name': name, 'argument': json.loads(argument)}, 'requires_approval': False}
        self.tokens[token] = plan
        return json.dumps({'token': token, 'plan': plan, 'expires_at': time.monotonic() + 30})

    @method()
    def Apply(self, token: 's') -> 's':
        self.applied.append(self.tokens.pop(token))
        return 'Fixture applied.'


@unittest.skipUnless(os.environ.get('AURORA_MCP_TEST_BUS') == '1', 'Needs isolated test bus')
class LiveAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_and_shortcut_use_mcp_and_exact_consent(self):
        import time
        from types import SimpleNamespace
        from aurora_assistant.mcp_desktop import MCPDesktop
        from unittest.mock import patch
        service = await MessageBus().connect()
        fixture = AdapterFixture()
        service.export('/org/aurora/Desktop', fixture)
        await service.request_name('org.aurora.Desktop')
        try:
            with tempfile.TemporaryDirectory() as directory:
                script = Path(directory) / 'server'
                source = Path(__file__).resolve().parents[2] / 'mcp'
                script.write_text(f'#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(source)!r})\nfrom aurora_mcdbus import main\nmain()\n')
                script.chmod(0o700)
                consent = Consent(AsyncMock(return_value=False))
                transport = MCPTransport(str(script), consent)
                async with transport.connect():
                    bus = MCPBusAccess({}, transport, consent)
                    executor = SimpleNamespace(dbus_actions=SimpleNamespace(registry={}))
                    desktop = MCPDesktop(bus, executor)
                    # Any inherited direct transport call is a test failure.
                    with patch.object(bus, 'call', AsyncMock(side_effect=AssertionError('direct call'))):
                        self.assertEqual((await desktop.describe())['description']['version'], 1)
                        self.assertEqual((await desktop.read(Action('desktop_read', 'clock')))['reply'], 'fixture read')
                        denied = await desktop.prepare(Action('mute', True))
                        self.assertTrue(denied['requires_approval'])
                        with self.assertRaisesRegex(MCPFailure, '^mcp.invalid_consent$'):
                            await desktop.execute(denied)
                        self.assertEqual(fixture.applied, [])
                        plan = await desktop.prepare(Action('mute', True))
                        self.assertLess(plan['expires_at'], time.monotonic() + 31)
                        changed = {**plan, 'adapter_plan': {'action': {'name': 'mute', 'argument': False}}}
                        with self.assertRaisesRegex(MCPFailure, '^mcp.invalid_consent$'):
                            desktop.authorize_plan([changed])
                        desktop.authorize_plan([plan])
                        self.assertEqual(await desktop.execute(plan), 'Fixture applied.')
                        self.assertEqual(fixture.applied[0]['action'], {'name': 'mute', 'argument': True})
                        # The query tool must never provide an Apply bypass.
                        with self.assertRaisesRegex(MCPFailure, '^mcp.refused$'):
                            await transport.call('desktop_query', {'method': 'Apply', 'args': '["0"]',
                                                                 'expected_owner': service.unique_name})
                        self.assertEqual(len(fixture.applied), 1)
                        executor.dbus_actions.registry['probe'] = {
                            'bus': 'session', 'destination': 'org.aurora.Desktop', 'path': '/org/aurora/Desktop',
                            'interface': 'org.aurora.Desktop1', 'member': 'Read', 'signature': 's',
                            'arguments': ['clock'], 'expectedReply': ['{"reply":"fixture read"}']}
                        shortcut = await desktop.prepare(Action('dbus', 'probe'))
                        desktop.authorize_plan([shortcut])
                        await desktop.execute(shortcut)
                        executor.dbus_actions.registry['probe']['signature'] = 'i'
                        with self.assertRaisesRegex(ValueError, 'Configured signature'):
                            await desktop.prepare(Action('dbus', 'probe'))
        finally:
            service.disconnect()
            await service.wait_for_disconnect()
