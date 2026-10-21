"""Private test bus only. Never uses an existing desktop service."""
import json
import os
import unittest
from dbus_fast.aio import MessageBus
from dbus_fast.constants import PropertyAccess
from dbus_fast.service import ServiceInterface, method, dbus_property
from fastmcp import Client
from fastmcp.exceptions import ToolError
import aurora_mcdbus as server


class Fixture(ServiceInterface):
    def __init__(self):
        super().__init__('org.kde.AuroraMcpFixture')
        self.calls = []
        self.enabled = False

    @method()
    def SetLevel(self, level: 'i') -> 'i':
        self.calls.append(level)
        return level

    @dbus_property(access=PropertyAccess.READWRITE)
    def Enabled(self) -> 'b':
        return self.enabled

    @Enabled.setter
    def Enabled(self, value: 'b'):
        self.enabled = value


@unittest.skipUnless(os.environ.get('AURORA_MCP_TEST_BUS') == '1', 'Needs isolated test bus')
class LiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bus = await MessageBus().connect()
        self.fixture = Fixture()
        self.bus.export('/Fixture', self.fixture)
        self.service = 'org.kde.AuroraMcpFixture'
        await self.bus.request_name(self.service)
        self.endpoint = {'bus': 'session', 'service': self.service, 'object_path': '/Fixture',
                         'interface': self.service, 'expected_owner': self.bus.unique_name}

    async def asyncTearDown(self):
        self.bus.disconnect()
        await self.bus.wait_for_disconnect()

    async def accept(self, *args):
        return {'confirm': True}

    async def test_describe_call_and_property(self):
        async with Client(server.mcp, elicitation_handler=self.accept) as client:
            response = await client.call_tool('describe_object', {
                'bus': 'session', 'service': self.service, 'object_path': '/Fixture'})
            self.assertEqual(response.data['owner'], self.bus.unique_name)
            self.assertEqual(response.data['description']['owner'], self.bus.unique_name)
            self.assertIn(self.service, [i['name'] for i in response.data['description']['interfaces']])
            await client.call_tool('call_method', {**self.endpoint, 'method': 'SetLevel', 'args': '[50]'})
            await client.call_tool('set_property', {**self.endpoint, 'property_name': 'Enabled',
                                                   'value': 'true', 'expected_value': 'false'})
        self.assertEqual(self.fixture.calls, [50])
        self.assertTrue(self.fixture.enabled)

    async def test_denial_reaches_confirmation_without_mutation(self):
        prompts = []
        async def deny(message, *args):
            prompts.append(json.loads(message))
            return {'confirm': False}
        async with Client(server.mcp, elicitation_handler=deny) as client:
            for tool, arguments in [
                ('call_method', {'method': 'SetLevel', 'args': '[50]'}),
                ('set_property', {'property_name': 'Enabled', 'value': 'true', 'expected_value': 'false'}),
            ]:
                with self.subTest(tool=tool), self.assertRaisesRegex(ToolError, '^confirmation_denied$'):
                    await client.call_tool(tool, {**self.endpoint, **arguments})
        self.assertEqual(len(prompts), 2)
        self.assertEqual(prompts[0]['method'], 'SetLevel')
        self.assertEqual(prompts[0]['args'], [50])
        self.assertEqual(prompts[1]['property'], 'Enabled')
        self.assertIs(prompts[1]['value'], True)
        self.assertTrue(all(p['owner'] == self.bus.unique_name for p in prompts))
        self.assertEqual(self.fixture.calls, [])
        self.assertFalse(self.fixture.enabled)

    async def test_stale_owner_does_not_prompt_or_mutate(self):
        prompts = []
        async def accept(message, *args):
            prompts.append(message)
            return {'confirm': True}
        async with Client(server.mcp, elicitation_handler=accept) as client:
            with self.assertRaisesRegex(ToolError, '^owner_mismatch$'):
                await client.call_tool('call_method', {**self.endpoint, 'expected_owner': ':999.999',
                                                       'method': 'SetLevel', 'args': '[50]'})
        self.assertEqual(prompts, [])
        self.assertEqual(self.fixture.calls, [])
        self.assertFalse(self.fixture.enabled)


if __name__ == '__main__':
    unittest.main()
