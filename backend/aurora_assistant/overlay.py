"""Client of the supplied, unchanged VoiceOverlay1 contract."""
import asyncio
import logging
from .telemetry import event

BUS = "org.example.VoiceOverlay"
PATH = "/org/example/VoiceOverlay"
INTERFACE = "org.example.VoiceOverlay1"


class Overlay:
    def __init__(self):
        self.bus = None

    async def connect(self):
        from dbus_next.aio import MessageBus
        self.bus = await MessageBus().connect()

    async def call(self, member, signature="", body=None):
        from dbus_next import Message, MessageType
        try:
            reply = await asyncio.wait_for(self.bus.call(Message(
                destination=BUS, path=PATH, interface=INTERFACE,
                member=member, signature=signature, body=body or [])), 1)
            if reply.message_type == MessageType.ERROR:
                raise RuntimeError("Overlay rejected method")
        except (OSError, RuntimeError, asyncio.TimeoutError):
            # No proxy is cached: a restarted overlay can reacquire the same name.
            event("overlay.unavailable", member=member)

    async def state(self, value):
        event("overlay.state", state=value)
        await self.call("SetState", "s", [value])

    async def message(self, value):
        await self.call("SetMessage", "s", [value[:8192]])

    async def level(self, value):
        await self.call("SetLevel", "d", [float(max(0, min(1, value)))])

    async def reset(self):
        event("overlay.reset")
        await self.call("Reset")

    def close(self):
        if self.bus:
            self.bus.disconnect()
