"""Run with PYTHONPATH=mcp and FastMCP 3.4.7 / mcdbus 2026.3.6.3."""
import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from dbus_fast import Variant
import aurora_mcdbus as server

XML = '''<node><interface name="org.kde.AuroraTest">
<method name="SetLevel"><arg name="level" type="i" direction="in"/></method>
<method name="Options"><arg name="options" type="a{sv}" direction="in"/></method>
<property name="Enabled" type="b" access="readwrite"/>
</interface></node>'''
ENDPOINT = dict(bus='session', service='org.kde.AuroraTest', object_path='/',
                interface='org.kde.AuroraTest', expected_owner=':1.20')


STANDARD_DOCTYPE = ('<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"\n'
                    '"http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">\n')


class IntrospectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_describe_accepts_standard_declaration(self):
        xml = STANDARD_DOCTYPE + XML
        connection = object()
        ctx = SimpleNamespace(lifespan_context=SimpleNamespace(
            get_bus=AsyncMock(return_value=connection)))
        with patch.object(server, 'owner', AsyncMock(return_value=':1.20')), \
                patch.object(server, 'send', AsyncMock(return_value=[xml])):
            actual, unique, node, raw = await server.describe(
                ctx, 'session', 'org.kde.AuroraTest', '/')
        self.assertIs(actual, connection)
        self.assertEqual(unique, ':1.20')
        self.assertEqual(raw, xml)
        self.assertEqual(node.find('interface').get('name'), 'org.kde.AuroraTest')

    def test_plain_xml_and_predefined_entities(self):
        self.assertEqual(server.parse_introspection('<node name="a&amp;b"/>').get('name'), 'a&b')

    def test_rejects_entities_and_custom_dtd(self):
        documents = [
            '<!DOCTYPE node [<!ENTITY x "expanded">]><node>&x;</node>',
            '<!DOCTYPE node [<!ENTITY x SYSTEM "file:///etc/passwd">]><node>&x;</node>',
            '<!DOCTYPE node [<!ENTITY % x SYSTEM "https://invalid.test/evil.dtd">%x;]><node/>',
            '<!DOCTYPE node SYSTEM "https://invalid.test/evil.dtd"><node/>',
            STANDARD_DOCTYPE.replace('>\n', ' [<!ENTITY x "expanded">]>\n') + '<node>&x;</node>',
            '<!DOCTYPE node [<!ENTITY a "123"><!ENTITY b "&a;&a;&a;">]><node>&b;</node>',
        ]
        for xml in documents:
            with self.subTest(xml=xml), self.assertRaisesRegex(ToolError, '^DTD and entity declarations are unsupported$'):
                server.parse_introspection(xml)

    def test_size_limit_is_bytes_and_precedes_parsing(self):
        for xml in ['x' * (server.MAX_XML + 1), '<node>' + 'é' * (server.MAX_XML // 2) + '</node>']:
            with self.subTest(length=len(xml)), \
                    patch.object(server.expat, 'ParserCreate') as parser, \
                    self.assertRaisesRegex(ToolError, '^Invalid or oversized introspection$'):
                server.parse_introspection(xml)
            parser.assert_not_called()

    def test_invalid_xml_and_root(self):
        for xml, error in [('<node>', 'Invalid introspection XML'),
                           ('<other/>', 'Invalid introspection root')]:
            with self.subTest(xml=xml), self.assertRaisesRegex(ToolError, '^' + error + '$'):
                server.parse_introspection(xml)


class Types(unittest.TestCase):
    def test_compound_types(self):
        result = server.typed('a{sv}', {'Enabled': {'signature': 'b', 'value': True}})
        self.assertIsInstance(result['Enabled'], Variant)
        self.assertEqual(result['Enabled'].value, True)
        self.assertEqual(server.typed('(ias)', [4, ['x']]), [4, ['x']])
        self.assertEqual(server.typed('ay', [0, 255]), bytes([0, 255]))

    def test_invalid_values(self):
        for sig, value in [('i', True), ('b', 1), ('i', 2**40), ('d', float('nan')),
                           ('v', 3), ('h', 1), ('ai', [True]), ('a{iv}', {'1': 2})]:
            with self.subTest(sig=sig, value=value), self.assertRaises(ToolError):
                server.typed(sig, value)

    def test_json_rejects_duplicates_nonfinite_and_oversized(self):
        for text in ['{"a":1,"a":2}', 'NaN', '[Infinity]', '"' + 'x'*server.MAX_ARGS + '"']:
            with self.subTest(text=text[:50]), self.assertRaises(ToolError):
                server.parse_json(text)


class ConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_explicit_true_accepts(self):
        ctx = SimpleNamespace(elicit=AsyncMock())
        for result in [None, DeclinedElicitation(), AcceptedElicitation(data=server.Confirmation(confirm=False))]:
            ctx.elicit.return_value = result
            with self.assertRaises(ToolError):
                await server.confirm(ctx, {'test': True})
        ctx.elicit.return_value = AcceptedElicitation(data=server.Confirmation(confirm=True))
        await server.confirm(ctx, {'test': True})

    async def test_error_and_timeout_deny_even_with_fallback_enabled(self):
        with patch.dict(os.environ, {'MCDBUS_NOTIFY_CONFIRM': '1'}):
            for error in [RuntimeError('unavailable'), TimeoutError()]:
                ctx = SimpleNamespace(elicit=AsyncMock(side_effect=error))
                with self.assertRaisesRegex(ToolError, 'confirmation_unavailable'):
                    await server.confirm(ctx, {})
            ctx = SimpleNamespace(elicit=AsyncMock(side_effect=lambda *a: None))
            async def wait(*args):
                await asyncio.sleep(60)
            ctx.elicit.side_effect = wait
            with patch.object(server, 'CONFIRM_TIMEOUT', 0.001):
                with self.assertRaisesRegex(ToolError, 'confirmation_unavailable'):
                    await server.confirm(ctx, {})

    async def test_cancel_propagates(self):
        with self.assertRaises(asyncio.CancelledError):
            await server.confirm(SimpleNamespace(elicit=AsyncMock(side_effect=asyncio.CancelledError())), {})


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.messages = []
        self.connection = object()
        self.describe = patch.object(server, 'describe', AsyncMock(return_value=(
            self.connection, ':1.20', server.ElementTree.fromstring(XML), XML)))
        self.describe_mock = self.describe.start()
        self.owner = patch.object(server, 'owner', AsyncMock(return_value=':1.20'))
        self.owner_mock = self.owner.start()
        self.send = patch.object(server, 'send', AsyncMock(return_value=[]))
        self.send_mock = self.send.start()
        self.addCleanup(self.describe.stop)
        self.addCleanup(self.owner.stop)
        self.addCleanup(self.send.stop)

    async def accept(self, message, response_type, params, context):
        self.messages.append(json.loads(message))
        return {'confirm': True}

    async def test_tools_exclude_bypass_and_signatures(self):
        async with Client(server.mcp) as client:
            tools = {t.name: t for t in await client.list_tools()}
        self.assertEqual(set(tools), {'describe_object', 'call_method', 'set_property'})
        self.assertNotIn('signature', tools['call_method'].inputSchema['properties'])
        self.assertNotIn('signature', tools['set_property'].inputSchema['properties'])

    async def test_caller_signature_is_rejected(self):
        async with Client(server.mcp, elicitation_handler=self.accept) as client:
            with self.assertRaises(ToolError):
                await client.call_tool('call_method', {**ENDPOINT, 'method': 'SetLevel',
                                                       'args': '[50]', 'signature': 's'})
        self.send_mock.assert_not_awaited()
        self.assertFalse(self.messages)

    async def test_call_uses_introspection_and_unique_owner(self):
        async with Client(server.mcp, elicitation_handler=self.accept) as client:
            await client.call_tool('call_method', {**ENDPOINT, 'method': 'SetLevel', 'args': '[50]'})
        self.assertEqual(self.send_mock.call_args.args,
            (self.connection, ':1.20', '/', 'org.kde.AuroraTest', 'SetLevel', 'i', [50]))
        self.assertEqual(self.messages[0]['args'], [50])
        self.assertEqual(self.messages[0]['owner'], ':1.20')

    async def test_unavailable_confirmation_never_invokes(self):
        async with Client(server.mcp) as client:
            with self.assertRaisesRegex(ToolError, '^confirmation_unavailable$'):
                await client.call_tool('call_method', {**ENDPOINT, 'method': 'SetLevel', 'args': '[50]'})
        self.send_mock.assert_not_awaited()

    async def test_owner_change_after_approval_never_invokes(self):
        self.owner_mock.return_value = ':1.21'
        async with Client(server.mcp, elicitation_handler=self.accept) as client:
            with self.assertRaisesRegex(ToolError, '^owner_mismatch$'):
                await client.call_tool('call_method', {**ENDPOINT, 'method': 'SetLevel', 'args': '[50]'})
        self.assertEqual(len(self.messages), 1)
        self.send_mock.assert_not_awaited()

    async def test_schema_change_after_approval_never_invokes(self):
        self.describe_mock.side_effect = [
            (self.connection, ':1.20', server.ElementTree.fromstring(XML), XML),
            (self.connection, ':1.20', server.ElementTree.fromstring(XML.replace('type="i"', 'type="s"')), XML)]
        async with Client(server.mcp, elicitation_handler=self.accept) as client:
            with self.assertRaisesRegex(ToolError, '^schema_changed$'):
                await client.call_tool('call_method', {**ENDPOINT, 'method': 'SetLevel', 'args': '[50]'})
        self.assertEqual(len(self.messages), 1)
        self.send_mock.assert_not_awaited()

    async def test_type_error_does_not_prompt(self):
        async with Client(server.mcp, elicitation_handler=self.accept) as client:
            with self.assertRaisesRegex(ToolError, '^type_error$'):
                await client.call_tool('call_method', {**ENDPOINT, 'method': 'SetLevel', 'args': '[true]'})
        self.assertFalse(self.messages)
        self.send_mock.assert_not_awaited()

    async def test_property_changed_does_not_write(self):
        self.send_mock.return_value = [Variant('b', True)]
        async with Client(server.mcp, elicitation_handler=self.accept) as client:
            with self.assertRaisesRegex(ToolError, '^property_changed$'):
                await client.call_tool('set_property', {**ENDPOINT, 'property_name': 'Enabled',
                                                        'value': 'true', 'expected_value': 'false'})
        self.assertEqual(len(self.messages), 1)
        self.assertEqual(self.send_mock.await_count, 1)
        self.assertEqual(self.send_mock.call_args.args[4], 'Get')

    async def test_approval_expiry_after_confirmation_never_invokes(self):
        async def accept_and_expire(*args):
            self.messages.append('prompted')
            clock.return_value = 201
            return {'confirm': True}
        with patch.object(server, 'monotonic', return_value=100) as clock:
            async with Client(server.mcp, elicitation_handler=accept_and_expire) as client:
                with self.assertRaisesRegex(ToolError, '^approval_expired$'):
                    await client.call_tool('call_method', {**ENDPOINT, 'method': 'SetLevel',
                                                           'args': '[50]', 'expires_at': 200})
        self.assertEqual(self.messages, ['prompted'])
        self.send_mock.assert_not_awaited()

    async def test_property_write_and_readback(self):
        self.send_mock.side_effect = [[Variant('b', False)], [], [Variant('b', True)]]
        async with Client(server.mcp, elicitation_handler=self.accept) as client:
            await client.call_tool('set_property', {**ENDPOINT, 'property_name': 'Enabled',
                                                   'value': 'true', 'expected_value': 'false'})
        self.assertEqual([c.args[4] for c in self.send_mock.call_args_list], ['Get', 'Set', 'Get'])
        self.assertTrue(all(c.args[1] == ':1.20' for c in self.send_mock.call_args_list))


if __name__ == '__main__':
    unittest.main()
