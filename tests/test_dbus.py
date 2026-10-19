"""Run under dbus-run-session; no KDE display is needed."""
import asyncio
import os
import unittest
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method
from aurora_assistant.overlay import Overlay, BUS, PATH, INTERFACE


class Contract(ServiceInterface):
    def __init__(self):
        super().__init__(INTERFACE)
        self.state = "idle"
        self.text = ""
        self.level = 0.

    @method()
    def SetState(self, value: 's') -> 'b':
        self.state = value
        return True

    @method()
    def SetMessage(self, value: 's'):
        self.text = value

    @method()
    def SetLevel(self, value: 'd'):
        self.level = value

    @method()
    def Reset(self):
        self.state, self.text, self.level = "idle", "", 0.


@unittest.skipUnless(os.environ.get("DBUS_SESSION_BUS_ADDRESS"), "Needs a test session bus")
class BusTests(unittest.IsolatedAsyncioTestCase):
    async def test_pinned_signatures_and_owner_restart(self):
        server = await MessageBus().connect()
        contract = Contract()
        server.export(PATH, contract)
        await server.request_name(BUS)
        client = Overlay()
        await client.connect()
        try:
            await client.state("listening")
            await client.message("turn on")
            await client.message("turn off")
            await client.level(0.7)
            self.assertEqual((contract.state, contract.text, contract.level), ("listening", "turn off", 0.7))
            await server.release_name(BUS)
            await client.message("dropped while absent")
            await server.request_name(BUS)
            await client.message("restored")
            self.assertEqual(contract.text, "restored")
            await client.reset()
            self.assertEqual(contract.state, "idle")
        finally:
            client.close()
            server.disconnect()
