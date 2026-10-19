"""Configured D-Bus capabilities; model output cannot choose a bus endpoint."""
import asyncio
import copy


def validate_registry(registry):
    from dbus_next import Message
    from dbus_next.signature import SignatureTree
    if not isinstance(registry, dict):
        raise ValueError("dbus_actions must be an object")
    for alias, item in registry.items():
        if not isinstance(alias, str) or not alias or not isinstance(item, dict):
            raise ValueError("Invalid D-Bus action")
        if item.get("bus", "session") not in ("session", "system"):
            raise ValueError("Invalid D-Bus bus")
        for key in ("description", "destination", "path", "interface", "member"):
            if not isinstance(item.get(key), str) or not item[key]:
                raise ValueError(f"Missing D-Bus action field: {key}")
        signature, body = item.get("signature", ""), item.get("arguments", [])
        SignatureTree(signature).verify(body)
        Message(destination=item["destination"], path=item["path"],
                interface=item["interface"], member=item["member"],
                signature=signature, body=body)
        if item.get("expectedReply") is not None and not isinstance(item["expectedReply"], list):
            raise ValueError("expectedReply must be a list or null")
        if not isinstance(item.get("successMessage", ""), str):
            raise ValueError("successMessage must be text")
    return registry


class DBusActions:
    def __init__(self, registry, connect=None):
        self.registry = copy.deepcopy(validate_registry(registry))
        self.connect = connect or self._connect

    @staticmethod
    async def _connect(which):
        from dbus_next.aio import MessageBus
        from dbus_next import BusType
        return await MessageBus(bus_type=BusType.SESSION if which == "session" else BusType.SYSTEM).connect()

    async def execute(self, alias):
        from dbus_next import Message, MessageType
        if type(alias) is not str or alias not in self.registry:
            raise ValueError("D-Bus action is not registered")
        item = self.registry[alias]
        bus = None
        try:
            async with asyncio.timeout(10):
                bus = await self.connect(item.get("bus", "session"))
                reply = await bus.call(Message(
                    destination=item["destination"], path=item["path"],
                    interface=item["interface"], member=item["member"],
                    signature=item.get("signature", ""),
                    body=copy.deepcopy(item.get("arguments", []))))
            if reply.message_type != MessageType.METHOD_RETURN:
                raise RuntimeError("D-Bus method failed")
            if item.get("expectedReply") is not None and reply.body != item["expectedReply"]:
                raise RuntimeError("D-Bus method returned an unexpected result")
            return item.get("successMessage", "D-Bus action completed.")
        finally:
            if bus:
                bus.disconnect()
