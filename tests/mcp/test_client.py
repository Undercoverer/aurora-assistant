"""Client/server integration over a real stdio child, without desktop access."""
import asyncio
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock
from aurora_assistant.mcp_client import Consent, MCPTransport, MCPFailure
from aurora_assistant.mcp_bus import MCPBusAccess


class ClientProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_describe_refusal_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'server'
            source = Path(__file__).resolve().parents[2] / 'mcp'
            script.write_text(f'#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(source)!r})\nfrom aurora_mcdbus import main\nmain()\n')
            script.chmod(0o700)
            consent = Consent(AsyncMock(return_value=False))
            transport = MCPTransport(str(script), consent)
            async with asyncio.timeout(20):
                async with transport.connect():
                    with self.assertRaisesRegex(MCPFailure, '^mcp.refused$'):
                        await transport.call('describe_object', {'bus': 'invalid', 'service': 'org.kde.Test', 'object_path': '/'})
            self.assertIsNone(transport.session)
            self.assertIsNone(consent.active)

    async def test_missing_executable_fails_startup(self):
        transport = MCPTransport('/does/not/exist/aurora-mcdbus', Consent(None))
        with self.assertRaises(Exception):
            async with transport.connect():
                self.fail('Missing server must not start')


class ClientExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_direct_fallback_after_transport_failure(self):
        consent = Consent(None)
        transport = AsyncMock()
        transport.call.side_effect = MCPFailure('mcp.transport_failed')
        bus = MCPBusAccess({}, transport, consent)
        bus.call = AsyncMock()
        request = {'contract': 'aurora-mcdbus-1', 'bus': 'session', 'service': 'org.kde.Test',
                   'owner': ':1.2', 'object_path': '/', 'interface': 'org.kde.Test',
                   'method': 'SetLevel', 'args': [50], 'signature': 'i'}
        plan = consent.prepare({'action': {'name': 'dbus_call'}, 'requires_approval': True}, request)
        consent.authorize([plan])
        with self.assertRaisesRegex(MCPFailure, '^mcp.transport_failed$'):
            await bus.execute(plan)
        bus.call.assert_not_awaited()
        transport.call.assert_awaited_once()
        self.assertIsNone(consent.active)
        with self.assertRaisesRegex(MCPFailure, '^mcp.invalid_consent$'):
            await bus.execute(plan)
