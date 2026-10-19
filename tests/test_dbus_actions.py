import copy
import unittest
from unittest.mock import AsyncMock, Mock
from dbus_next import Message, MessageType
from aurora_assistant.actions import schema, validate
from aurora_assistant.dbus_actions import DBusActions, validate_registry

REGISTRY = {"jade_theme": {
    "description": "Change the assistant overlay colors to northern jade",
    "destination": "org.example.VoiceOverlay", "path": "/org/example/VoiceOverlay",
    "interface": "org.example.VoiceOverlay1", "member": "LoadPalette",
    "signature": "s", "arguments": ["northern-jade"],
    "expectedReply": [True], "successMessage": "Overlay palette changed."
}}


class RegistryTests(unittest.TestCase):
    def test_only_registered_aliases_are_accepted(self):
        good = {"actions": [{"name": "dbus", "argument": "jade_theme"}], "reply": ""}
        self.assertEqual(validate(good, {}, REGISTRY)[0][0].argument, "jade_theme")
        for arg in ("org.freedesktop.systemd1", {"destination": "anything"}, []):
            with self.assertRaises(ValueError):
                validate({"actions": [{"name": "dbus", "argument": arg}], "reply": ""}, {}, REGISTRY)
        with self.assertRaises(ValueError):
            validate(good, {})

    def test_schema_describes_capabilities(self):
        variants = schema({}, REGISTRY)["properties"]["actions"]["items"]["anyOf"]
        dbus = variants[-1]["properties"]["argument"]["oneOf"]
        self.assertEqual(dbus[0]["const"], "jade_theme")
        self.assertEqual(dbus[0]["description"], REGISTRY["jade_theme"]["description"])

    def test_invalid_static_argument_rejected(self):
        invalid = copy.deepcopy(REGISTRY)
        invalid["jade_theme"]["arguments"] = [123]
        with self.assertRaises(Exception):
            validate_registry(invalid)


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_endpoint_arguments_and_cleanup(self):
        bus = Mock()
        bus.call = AsyncMock(return_value=Message(message_type=MessageType.METHOD_RETURN,
                                                  reply_serial=1, signature='b', body=[True]))
        connect = AsyncMock(return_value=bus)
        action = DBusActions(REGISTRY, connect)
        result = await action.execute("jade_theme")
        connect.assert_awaited_once_with("session")
        message = bus.call.call_args.args[0]
        self.assertEqual(message.member, "LoadPalette")
        self.assertEqual(message.body, ["northern-jade"])
        self.assertEqual(result, "Overlay palette changed.")
        bus.disconnect.assert_called_once()

    async def test_rejected_result_does_not_report_success(self):
        bus = Mock()
        bus.call = AsyncMock(return_value=Message(message_type=MessageType.METHOD_RETURN,
                                                  reply_serial=1, signature='b', body=[False]))
        with self.assertRaises(RuntimeError):
            await DBusActions(REGISTRY, AsyncMock(return_value=bus)).execute("jade_theme")
        bus.disconnect.assert_called_once()

    async def test_bus_error_does_not_report_success(self):
        bus = Mock()
        bus.call = AsyncMock(return_value=Message(message_type=MessageType.ERROR, reply_serial=1,
                                                  error_name='org.freedesktop.DBus.Error.AccessDenied'))
        with self.assertRaises(RuntimeError):
            await DBusActions(REGISTRY, AsyncMock(return_value=bus)).execute("jade_theme")
        bus.disconnect.assert_called_once()
