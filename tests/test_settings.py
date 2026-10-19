import unittest
from unittest.mock import AsyncMock, Mock
from dbus_next import Variant
from dbus_next.introspection import Node
from aurora_assistant.actions import Action, validate
from aurora_assistant.settings import BusAccess, DesktopSettings, typed

XML = '''<node><interface name="org.kde.Test"><property name="Enabled" type="b" access="readwrite"/>
<method name="SetLevel"><arg name="value" type="i" direction="in"/></method></interface></node>'''
ENDPOINT = {'bus': 'session', 'destination': 'org.kde.Test', 'path': '/', 'interface': 'org.kde.Test'}


class TypeTests(unittest.TestCase):
    def test_argument_validation(self):
        for name, arg in [('microphone_mute', True), ('theme', 'org.kde.breezedark.desktop'),
                          ('dbus_set', {**ENDPOINT, 'property': 'Enabled', 'valueJson': 'true'})]:
            self.assertEqual(validate({'actions': [{'name': name, 'argument': arg}], 'reply': ''}, {}, settings=True)[0][0].name, name)
        for name, arg in [('theme', '--apply=evil'), ('microphone_mute', 1),
                          ('dbus_set', {**ENDPOINT, 'property': 'Enabled', 'valueJson': 'true', 'extra': 'x'})]:
            with self.assertRaises(ValueError):
                validate({'actions': [{'name': name, 'argument': arg}], 'reply': ''}, {}, settings=True)

    def test_introspection_types_are_enforced(self):
        for signature, value in [('b', 1), ('i', True), ('i', 2**40), ('d', float('nan')), ('h', 3)]:
            with self.assertRaises(Exception):
                typed(signature, value)
        self.assertEqual(typed('as', ['a', 'b']), ['a', 'b'])
        self.assertEqual(typed('v', {'signature': 'b', 'value': True}).value, True)

    def test_sensitive_services_are_not_discoverable(self):
        bus = BusAccess({'sessionPrefixes': ['']})
        for name in ('org.freedesktop.secrets', 'org.kde.kwalletd6', 'org.kde.konsole', ':1.2'):
            self.assertFalse(bus.allowed('session', name))
        self.assertTrue(bus.allowed('session', 'org.kde.Test'))


class BusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bus = BusAccess({})
        self.bus.describe = AsyncMock(return_value=(':1.2', Node.parse(XML)))
        self.bus.owner = AsyncMock(return_value=':1.2')
        self.bus.get = AsyncMock(return_value=Variant('b', False))
        self.bus.call = AsyncMock(return_value=[])
        self.action = Action('dbus_set', {**ENDPOINT, 'property': 'Enabled', 'valueJson': 'true'})

    async def test_write_prepared_then_verified(self):
        prepared = await self.bus.prepare(self.action)
        self.assertTrue(prepared['requires_approval'])
        self.bus.get.side_effect = [Variant('b', False), Variant('b', True)]
        self.assertIn('true', await self.bus.execute(prepared))
        self.assertEqual(self.bus.call.call_args.args[4], 'Set')

    async def test_changed_state_prevents_write(self):
        prepared = await self.bus.prepare(self.action)
        self.bus.get.return_value = Variant('b', True)
        with self.assertRaisesRegex(RuntimeError, 'changed since'):
            await self.bus.execute(prepared)
        self.bus.call.assert_not_awaited()

    async def test_restarted_service_prevents_write(self):
        prepared = await self.bus.prepare(self.action)
        self.bus.owner.return_value = ':1.3'
        with self.assertRaisesRegex(RuntimeError, 'restarted'):
            await self.bus.execute(prepared)
        self.bus.call.assert_not_awaited()

    async def test_type_mismatch_prevents_write(self):
        bad = Action('dbus_set', {**self.action.argument, 'valueJson': '123'})
        with self.assertRaises(ValueError):
            await self.bus.prepare(bad)
        self.bus.call.assert_not_awaited()

    async def test_theme_must_exist(self):
        desktop = DesktopSettings({}, self.bus, Mock())
        desktop.themes = AsyncMock(return_value=['org.kde.breeze.desktop'])
        with self.assertRaisesRegex(ValueError, 'not installed'):
            await desktop.prepare(Action('theme', 'invented.theme'))
