"""Session-bus adapter for desktop controls without a stable native D-Bus API.

This is a transport boundary, not a privilege boundary: the desktop user can
already run these operations. The controller retains review and approval policy.
"""
import argparse
import asyncio
import configparser
import json
import os
from pathlib import Path
import secrets
import time

from dbus_next import DBusError
from dbus_next.aio import MessageBus
from dbus_next.constants import NameFlag, RequestNameReply
from dbus_next.service import ServiceInterface, method
from .actions import Action, Executor, validate, schema
from .config import load
from .settings import BusAccess, DesktopSettings
from .native_media import NativeMedia

NAME = 'org.aurora.Desktop'
PATH = '/org/aurora/Desktop'
INTERFACE = 'org.aurora.Desktop1'
DESKTOP_ACTIONS = {'volume', 'mute', 'microphone_mute', 'media', 'theme', 'color_scheme',
                   'open_app', 'launch_app', 'open_url'}


def applications():
    """Enumerate visible XDG desktop IDs, respecting higher-priority tombstones."""
    roots = [os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))]
    roots += os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':')
    result, seen = {}, set()
    desktops = set(os.environ.get('XDG_CURRENT_DESKTOP', 'KDE').split(':'))
    for root in roots:
        directory = Path(root) / 'applications'
        for path in sorted(directory.rglob('*.desktop')):
            desktop_id = str(path.relative_to(directory)).replace('/', '-')
            if desktop_id in seen:
                continue
            seen.add(desktop_id)
            try:
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                parser.read(path, encoding='utf-8')
                entry = parser['Desktop Entry']
                if entry.get('Type') != 'Application' or entry.getboolean('Hidden', fallback=False) or entry.getboolean('NoDisplay', fallback=False):
                    continue
                only = set(filter(None, entry.get('OnlyShowIn', '').split(';')))
                exclude = set(filter(None, entry.get('NotShowIn', '').split(';')))
                if (only and not desktops & only) or desktops & exclude:
                    continue
                if len(desktop_id) <= 200 and not desktop_id.startswith('-'):
                    result[desktop_id] = entry.get('Name', desktop_id)[:200]
            except (OSError, ValueError, configparser.Error, KeyError):
                continue
    return result


class DesktopService(ServiceInterface):
    def __init__(self, config):
        super().__init__(INTERFACE)
        self.config = config
        self.executor = Executor(config['apps'], config['commands'])
        self.desktop = DesktopSettings(config['commands'], BusAccess({}), self.executor)
        self.media = NativeMedia(self.desktop.bus)
        self.pending = {}

    @method()
    def Describe(self) -> 's':
        """Advertise supported tools and argument schemas; no request matching."""
        variants = schema(self.config['apps'], settings=True)['properties']['actions']['items']['anyOf']
        return json.dumps({'version': 1, 'actions': [
            {'name': v['properties']['name']['const'],
             'description': v.get('description', v['properties']['name']['const']),
             'argument': v['properties']['argument']}
            for v in variants if v['properties']['name']['const'] in DESKTOP_ACTIONS | {'desktop_read'}]})

    @method()
    async def Read(self, topic: 's') -> 's':
        """Read the clock, audio, media, themes/colors, or application IDs as JSON."""
        try:
            if topic == 'clock':
                from datetime import datetime
                now = datetime.now().astimezone()
                return json.dumps({'iso': now.isoformat(), 'timezone': now.tzname(),
                                   'reply': now.strftime('It is %H:%M %Z on %A, %B %d, %Y.')})
            if topic == 'media':
                return json.dumps(await self.media.players())
            if topic == 'applications':
                return json.dumps(applications())
            if topic not in {'audio', 'media', 'themes', 'colors'}:
                raise ValueError('Unknown desktop read topic')
            return json.dumps(await self.desktop.read(Action('desktop_read', topic)))
        except Exception as exc:
            raise DBusError('org.aurora.Desktop.Error', str(exc)) from exc

    @method()
    async def Prepare(self, name: 's', argument_json: 's') -> 's':
        """Validate one desktop action and store its exact plan for 120 seconds."""
        try:
            if len(argument_json) > 4096 or name not in DESKTOP_ACTIONS:
                raise ValueError('Unsupported desktop action')
            actions, _ = validate({'actions': [{'name': name, 'argument': json.loads(argument_json)}], 'reply': ''}, self.config['apps'], settings=True)
            action = actions[0]
            if name == 'open_url':
                plan = {'action': {'name': name, 'argument': action.argument}, 'requires_approval': False}
            elif name in {'launch_app', 'open_app'}:
                desktop_id = action.argument if name == 'launch_app' else self.config['apps'][action.argument]
                if desktop_id not in applications():
                    raise ValueError('Application is not installed or visible')
                plan = {'action': {'name': 'launch_app', 'argument': desktop_id}, 'requires_approval': False}
            elif name == 'media':
                plan = await self.media.prepare(action)
            else:
                plan = await self.desktop.prepare(action)
            now = time.monotonic()
            self.pending = {k: v for k, v in self.pending.items() if v[0] > now}
            if len(self.pending) >= 64:
                raise ValueError('Too many pending desktop actions')
            token = secrets.token_hex(16)
            self.pending[token] = (now + 120, plan)
            return json.dumps({'token': token, 'plan': plan, 'expires_at': now + 120})
        except Exception as exc:
            raise DBusError('org.aurora.Desktop.Error', str(exc)) from exc

    @method()
    async def Apply(self, token: 's') -> 's':
        """Apply a prepared action once; reject unknown or expired tokens."""
        try:
            expires, plan = self.pending.pop(token)
            if time.monotonic() >= expires:
                raise ValueError('Desktop plan expired')
            if plan['action']['name'] == 'open_url':
                from .portal import open_url
                return await open_url(plan['action']['argument'])
            if plan.get('native_media'):
                return await self.media.execute(plan)
            if plan['action']['name'] == 'launch_app':
                desktop_id = plan['action']['argument']
                if desktop_id not in applications():
                    raise ValueError('Application is no longer installed or visible')
                await self.desktop.command('gtk-launch', desktop_id)
                return f'Requested {desktop_id} to open.'
            return await self.desktop.execute(plan)
        except Exception as exc:
            raise DBusError('org.aurora.Desktop.Error', str(exc)) from exc


class RemoteDesktop:
    """Controller transport: native D-Bus discovery plus the desktop adapter."""
    def __init__(self, bus, executor):
        self.bus, self.executor = bus, executor
        self.media = NativeMedia(bus)
        self.observed_owner = None

    async def describe(self):
        owner = await self.owner()
        raw = (await self.bus.call('session', owner, PATH, INTERFACE, 'Describe'))[0]
        if type(raw) is not str or len(raw.encode()) > 65536:
            raise ValueError('Desktop capability description exceeds size limit')
        value = json.loads(raw)
        self.observed_owner = owner
        return {'source': {'bus': 'session', 'destination': NAME, 'path': PATH,
                           'interface': INTERFACE, 'owner': owner}, 'description': value}

    async def owner(self):
        return (await self.bus.call('session', 'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetNameOwner', 's', [NAME]))[0]

    async def read(self, action):
        if action.name == 'desktop_read' and action.argument == 'media':
            return await self.media.players()
        if action.name.startswith('dbus_'):
            return await self.bus.read(action)
        return json.loads((await self.bus.call('session', NAME, PATH, INTERFACE, 'Read', 's', [action.argument]))[0])

    async def prepare(self, action):
        if action.name == 'media':
            return await self.media.prepare(action)
        if action.name in {'dbus_set', 'dbus_call'}:
            return await self.bus.prepare(action)
        if action.name == 'dbus':
            return {'action': {'name': action.name, 'argument': action.argument}, 'requires_approval': True,
                    'configured_call': self.executor.dbus_actions.registry[action.argument]}
        owner = await self.owner()
        if self.observed_owner is not None and owner != self.observed_owner:
            raise RuntimeError('Desktop capabilities changed owner; refresh discovery before preparing')
        reply = json.loads((await self.bus.call('session', owner, PATH, INTERFACE, 'Prepare', 'ss', [action.name, json.dumps(action.argument)]))[0])
        return {**reply['plan'], 'desktop_owner': owner, 'desktop_token': reply['token'],
                'expires_at': reply['expires_at']}

    async def execute(self, prepared):
        if prepared.get('native_media'):
            return await self.media.execute(prepared)
        name = prepared['action']['name']
        if name in {'dbus_set', 'dbus_call'}:
            return await self.bus.execute(prepared)
        if name == 'dbus':
            return await self.executor.execute(Action(**prepared['action']))
        if await self.owner() != prepared['desktop_owner']:
            raise RuntimeError('Desktop service restarted; prepare the request again')
        return (await self.bus.call('session', prepared['desktop_owner'], PATH, INTERFACE, 'Apply', 's', [prepared['desktop_token']]))[0]


async def serve(config):
    bus = await MessageBus().connect()
    try:
        bus.export(PATH, DesktopService(config))
        if await bus.request_name(NAME, NameFlag.DO_NOT_QUEUE) != RequestNameReply.PRIMARY_OWNER:
            raise RuntimeError('Desktop service name is already owned')
        await bus.wait_for_disconnect()
    finally:
        bus.disconnect()


def main():
    parser = argparse.ArgumentParser(description='Aurora desktop D-Bus adapter')
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    from .telemetry import configure
    config = load(args.config)
    configure(config)
    asyncio.run(serve(config))
