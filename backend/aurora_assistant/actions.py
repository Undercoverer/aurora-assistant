"""The model selects typed actions; it never supplies process arguments."""
import asyncio
from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    name: str
    argument: str | int | bool | dict | None = None


def schema(apps, dbus_actions=None, settings=False, web_search=False):
    dbus_actions = dbus_actions or {}
    def variant(name, kind=None):
        props = {"name": {"const": name}}
        if kind is not None:
            props["argument"] = kind
        return {"type": "object", "properties": props,
                "required": list(props), "additionalProperties": False}
    variants = [variant("volume", {"type": "integer", "minimum": 0, "maximum": 100}),
                variant("mute", {"type": "boolean"}),
                variant("media", {"enum": ["play", "pause", "play-pause", "next", "previous"]})]
    if settings:
        from .settings import action_schemas
        variants.extend(action_schemas())
    if web_search:
        variants.append(variant("web_search", {"type": "string", "minLength": 1, "maxLength": 512,
            "description": "A public web query derived only from the original user request. Search runs alone, with no desktop mutations."}))
    if apps:
        variants.append(variant("open_app", {"enum": sorted(apps)}))
    if dbus_actions:
        variants.append(variant("dbus", {"oneOf": [
            {"const": alias, "description": entry["description"]}
            for alias, entry in sorted(dbus_actions.items())]}))
    return {"type": "object", "additionalProperties": False,
            "required": ["actions", "reply"], "properties": {
                "actions": {"type": "array", "maxItems": 4, "items": {"anyOf": variants}},
                "reply": {"type": "string", "maxLength": 1000}}}


def validate(plan, apps, dbus_actions=None, settings=False, web_search=False):
    dbus_actions = dbus_actions or {}
    if type(plan) is not dict or set(plan) != {"actions", "reply"}:
        raise ValueError("Invalid plan fields")
    if type(plan["reply"]) is not str or len(plan["reply"]) > 1000:
        raise ValueError("Invalid reply")
    if type(plan["actions"]) is not list or len(plan["actions"]) > 4:
        raise ValueError("Invalid action count")
    result = []
    for item in plan["actions"]:
        if type(item) is not dict or set(item) != {"name", "argument"}:
            raise ValueError("Invalid action fields")
        name, arg = item["name"], item["argument"]
        if type(name) is not str:
            raise ValueError("Action name must be a string")
        valid = ((name == "volume" and type(arg) is int and 0 <= arg <= 100)
                 or (name == "mute" and type(arg) is bool)
                 or (name == "media" and type(arg) is str and arg in
                     {"play", "pause", "play-pause", "next", "previous"})
                 or (name == "open_app" and type(arg) is str and arg in apps)
                 or (name == "dbus" and type(arg) is str and arg in dbus_actions))
        if web_search and name == "web_search":
            valid = type(arg) is str and 0 < len(arg.strip()) <= 512
        if settings and not valid:
            from .settings import valid_action
            valid = valid_action(name, arg)
        if not valid:
            raise ValueError("Unsupported action or argument")
        result.append(Action(name, arg))
    return result, plan["reply"]


class Executor:
    def __init__(self, apps, commands, run=None, dbus_actions=None):
        self.apps, self.commands = apps, commands
        self.run = run or self._run
        self.dbus_actions = dbus_actions

    async def _run(self, argv):
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            async with asyncio.timeout(10):
                code = await proc.wait()
        except BaseException:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            raise
        if code:
            raise RuntimeError("Desktop action failed")

    async def execute(self, action):
        name, arg = action.name, action.argument
        if name == "dbus":
            if self.dbus_actions is None:
                raise ValueError("No D-Bus capabilities configured")
            return await self.dbus_actions.execute(arg)
        if name == "volume":
            argv = [self.commands["wpctl"], "set-volume", "@DEFAULT_AUDIO_SINK@", f"{arg}%"]
            response = f"Volume set to {arg} percent."
        elif name == "mute":
            argv = [self.commands["wpctl"], "set-mute", "@DEFAULT_AUDIO_SINK@", str(int(arg))]
            response = "Sound muted." if arg else "Sound unmuted."
        elif name == "media":
            argv = [self.commands["playerctl"], arg]
            response = "Media command completed."
        elif name == "open_app":
            # gtk-launch resolves a configured desktop entry; no arbitrary command line.
            argv = [self.commands["gtk-launch"], self.apps[arg]]
            response = f"Requested {arg} to open."
        else:
            raise ValueError("Unknown action")
        await self.run(argv)
        return response
