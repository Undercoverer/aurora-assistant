"""Typed settings discovery and execution. No shell or model-authored code."""
import asyncio
import json
import math
import os
import re
from dataclasses import asdict
from .telemetry import phase, event

READ_ACTIONS = {'desktop_read', 'dbus_list', 'dbus_inspect', 'dbus_get'}
DBUS_FIELDS = {'bus', 'destination', 'path', 'interface'}


def object_schema(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def action_schemas():
    text = {'type': 'string', 'maxLength': 512}
    endpoint = {'bus': {'enum': ['session', 'system']}, 'destination': text, 'path': text, 'interface': text}
    args = {
        'microphone_mute': {'type': 'boolean'},
        'theme': text,
        'launch_app': text,
        'open_url': {'type': 'string', 'maxLength': 2048},
        'color_scheme': text,
        'desktop_read': {'enum': ['audio', 'media', 'themes', 'colors', 'applications', 'clock']},
        'dbus_list': {'enum': ['session', 'system']},
        'dbus_inspect': object_schema({k: v for k, v in endpoint.items() if k != 'interface'}),
        'dbus_get': object_schema({**endpoint, 'property': text}),
        'dbus_set': object_schema({**endpoint, 'property': text, 'valueJson': {'type': 'string', 'maxLength': 4096}}),
        'dbus_call': object_schema({**endpoint, 'method': text, 'argumentsJson': {'type': 'string', 'maxLength': 4096}}),
    }
    descriptions = {
        'microphone_mute': 'Set default microphone mute to the requested boolean; true prevents further speech input.',
        'theme': 'Apply an installed Plasma global theme ID obtained from desktop_read themes.',
        'color_scheme': 'Apply an installed color scheme ID obtained from desktop_read colors.',
        'open_url': 'Open an HTTP(S) URL in the default browser through the desktop portal.',
        'launch_app': 'Open a visible installed desktop ID obtained from desktop_read applications.',
        'desktop_read': 'Read the local clock, installed apps, themes, colors, default audio state, or live MPRIS players without mutation.',
        'dbus_list': 'List currently running services in the permitted scope of the selected bus.',
        'dbus_inspect': 'Read interfaces, signatures, properties and child paths from a live object.',
        'dbus_get': 'Read a property on an observed interface using its live signature.',
        'dbus_set': 'Propose a typed read/write property change. valueJson contains one JSON value. Execution is subject to effect policy and destructive-action approval.',
        'dbus_call': 'Propose a live method call. argumentsJson is a positional JSON array. Execution is subject to effect policy and destructive-action approval.',
    }
    return [{**object_schema({'name': {'const': name}, 'argument': arg}), 'description': descriptions[name]}
            for name, arg in args.items()]


def valid_action(name, arg):
    if name == 'open_url':
        from .portal import valid_url
        return valid_url(arg)
    if name == 'microphone_mute':
        return type(arg) is bool
    if name == 'launch_app':
        return type(arg) is str and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,192}\.desktop', arg))
    if name in {'theme', 'color_scheme'}:
        return type(arg) is str and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,200}', arg))
    if name == 'desktop_read':
        return type(arg) is str and arg in {'audio', 'media', 'themes', 'colors', 'applications', 'clock'}
    if name == 'dbus_list':
        return type(arg) is str and arg in {'session', 'system'}
    fields = {
        'dbus_inspect': {'bus', 'destination', 'path'},
        'dbus_get': DBUS_FIELDS | {'property'},
        'dbus_set': DBUS_FIELDS | {'property', 'valueJson'},
        'dbus_call': DBUS_FIELDS | {'method', 'argumentsJson'},
    }
    if name not in fields or type(arg) is not dict or set(arg) != fields[name]:
        return False
    return (all(type(v) is str and 0 < len(v) <= (4096 if k.endswith('Json') else 512) for k, v in arg.items())
            and arg['bus'] in {'session', 'system'})


def plain(value):
    from dbus_next import Variant
    if isinstance(value, Variant):
        return plain(value.value)
    if isinstance(value, bytes):
        return list(value)
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    return value


def typed(signature, value):
    """Decode explicit nested variants, then enforce the introspected signature."""
    from dbus_next import Variant
    from dbus_next.signature import SignatureTree
    tree = SignatureTree(signature)
    if len(tree.types) != 1:
        raise ValueError('Expected one D-Bus value type')
    def convert(t, v):
        if type(v) is float and not math.isfinite(v):
            raise ValueError('Non-finite D-Bus values are unsupported')
        if t.token == 'v':
            if type(v) is not dict or set(v) != {'signature', 'value'}:
                raise ValueError('Variant requires signature and value')
            return Variant(v['signature'], typed(v['signature'], v['value']))
        if t.token == 'a':
            child = t.children[0]
            if child.token == '{':
                if type(v) is not dict:
                    raise ValueError('Expected D-Bus dictionary')
                return {convert(child.children[0], k): convert(child.children[1], x) for k, x in v.items()}
            if type(v) is not list:
                raise ValueError('Expected D-Bus array')
            if child.token == 'y':
                if any(type(x) is not int or not 0 <= x <= 255 for x in v):
                    raise ValueError('Expected byte integers, not booleans')
                return bytes(v)
            return [convert(child, x) for x in v]
        if t.token == '(':
            if type(v) is not list or len(v) != len(t.children):
                raise ValueError('Invalid D-Bus struct')
            return [convert(c, x) for c, x in zip(t.children, v)]
        if t.token in 'ynqiuxt' and type(v) is not int:
            raise ValueError('Expected integer, not boolean or float')
        if t.token == 'd' and type(v) not in (int, float):
            raise ValueError('Expected number, not boolean')
        if t.token == 'b' and type(v) is not bool:
            raise ValueError('Expected boolean')
        if t.token == 'h':
            raise ValueError('File-descriptor arguments are unsupported')
        return v
    result = convert(tree.types[0], value)
    tree.verify([result])
    return result


class BusAccess:
    def __init__(self, config):
        self.prefixes = {'session': config.get('sessionPrefixes', ['org.kde.', 'org.mpris.']),
                         'system': config.get('systemPrefixes', ['org.freedesktop.UPower'])}

    def allowed(self, bus, destination):
        return (bus in self.prefixes and not destination.startswith(':')
                and not any(word in destination.lower() for word in ('wallet', 'secrets', 'klauncher', 'konsole', 'krunner'))
                and any(p and (destination == p.rstrip('.') or destination.startswith(p.rstrip('.') + '.'))
                        for p in self.prefixes[bus]))

    async def call(self, bus, destination, path, interface, member, signature='', body=None):
        from dbus_next import Message, MessageType, BusType
        from dbus_next.aio import MessageBus
        with phase('dbus.call', bus=bus, destination=destination, interface=interface, member=member):
            connection = None
            try:
                async with asyncio.timeout(45 if interface == 'org.aurora.Desktop1' else 8):
                    connection = await MessageBus(bus_type=BusType.SESSION if bus == 'session' else BusType.SYSTEM).connect()
                    reply = await connection.call(Message(destination=destination, path=path, interface=interface,
                                                           member=member, signature=signature, body=body or []))
                if reply.message_type != MessageType.METHOD_RETURN:
                    event('dbus.rejected', error_name=reply.error_name)
                    raise RuntimeError('D-Bus request was rejected')
                return reply.body
            finally:
                if connection:
                    connection.disconnect()

    async def owner(self, arg):
        if not self.allowed(arg['bus'], arg['destination']):
            raise ValueError('D-Bus service is outside configured discovery scope')
        return (await self.call(arg['bus'], 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                                'org.freedesktop.DBus', 'GetNameOwner', 's', [arg['destination']]))[0]

    async def describe(self, arg):
        from dbus_next.introspection import Node
        owner = await self.owner(arg)
        xml = (await self.call(arg['bus'], owner, arg['path'], 'org.freedesktop.DBus.Introspectable', 'Introspect'))[0]
        if len(xml) > 131072:
            raise ValueError('D-Bus introspection is too large')
        return owner, Node.parse(xml)

    async def property(self, arg):
        owner, node = await self.describe(arg)
        interface = next((i for i in node.interfaces if i.name == arg['interface']), None)
        prop = next((p for p in interface.properties if p.name == arg['property']), None) if interface else None
        if prop is None:
            raise ValueError('Property does not exist on the inspected interface')
        return owner, prop

    async def get(self, arg, owner=None):
        if owner is None:
            owner, prop = await self.property(arg)
            if prop.access.value == 'write':
                raise ValueError('Property is write-only')
        return (await self.call(arg['bus'], owner, arg['path'], 'org.freedesktop.DBus.Properties',
                                'Get', 'ss', [arg['interface'], arg['property']]))[0]

    async def read(self, action):
        name, arg = action.name, action.argument
        if name == 'dbus_list':
            names = (await self.call(arg, 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                                     'org.freedesktop.DBus', 'ListNames'))[0]
            return sorted(n for n in names if self.allowed(arg, n))[:150]
        if name == 'dbus_get':
            return plain(await self.get(arg))
        owner, node = await self.describe(arg)
        return {'owner': owner, 'children': [n.name for n in node.nodes], 'interfaces': [
            {'name': i.name, 'properties': [{'name': p.name, 'signature': p.signature, 'access': p.access.value} for p in i.properties],
             'methods': [{'name': m.name, 'input': ''.join(a.signature for a in m.in_args),
                          'output': ''.join(a.signature for a in m.out_args),
                          'arguments': [{'name': a.name or '', 'signature': a.signature} for a in m.in_args]} for m in i.methods]} for i in node.interfaces]}

    async def prepare(self, action):
        arg = action.argument
        if action.name == 'dbus_set':
            owner, prop = await self.property(arg)
            if prop.access.value != 'readwrite':
                raise ValueError('Only readable, writable properties can be changed and verified')
            value = typed(prop.signature, json.loads(arg['valueJson']))
            old = await self.get(arg, owner)
            return {'action': asdict(action), 'owner': owner, 'signature': prop.signature,
                    'before': plain(old), 'after': plain(value), 'requires_approval': True}
        if arg['method'].lower() in {'loadscript', 'evaluatescript', 'runcommand', 'execute', 'starttransientunit'} or 'scripting' in arg['interface'].lower():
            raise ValueError('Generic code-execution methods are not settings capabilities')
        owner, node = await self.describe(arg)
        interface = next((i for i in node.interfaces if i.name == arg['interface']), None)
        method = next((m for m in interface.methods if m.name == arg['method']), None) if interface else None
        if method is None:
            raise ValueError('Method is absent from the inspected interface')
        signature = ''.join(a.signature for a in method.in_args)
        args = json.loads(arg['argumentsJson'])
        if type(args) is not list or len(args) != len(method.in_args):
            raise ValueError('Wrong number of method arguments')
        for a, v in zip(method.in_args, args):
            typed(a.signature, v)
        return {'action': asdict(action), 'owner': owner, 'signature': signature,
                'input_types': [a.signature for a in method.in_args], 'requires_approval': True,
                'warning': 'Method side effects cannot be inferred from its signature.'}

    async def execute(self, prepared):
        from dbus_next import Variant
        action = prepared['action']
        arg = action['argument']
        if await self.owner(arg) != prepared['owner']:
            raise RuntimeError('D-Bus service restarted; the plan must be prepared again')
        if action['name'] == 'dbus_set':
            if plain(await self.get(arg, prepared['owner'])) != prepared['before']:
                raise RuntimeError('Setting changed since review; the plan was not applied')
            value = typed(prepared['signature'], json.loads(arg['valueJson']))
            await self.call(arg['bus'], prepared['owner'], arg['path'], 'org.freedesktop.DBus.Properties',
                            'Set', 'ssv', [arg['interface'], arg['property'], Variant(prepared['signature'], value)])
            actual = plain(await self.get(arg, prepared['owner']))
            if actual != prepared['after']:
                raise RuntimeError('D-Bus write returned but readback did not match; inspect the setting')
            return f"{arg['property']} is now {json.dumps(actual)}."
        values = [typed(s, v) for s, v in zip(prepared['input_types'], json.loads(arg['argumentsJson']))]
        result = await self.call(arg['bus'], prepared['owner'], arg['path'], arg['interface'], arg['method'], prepared['signature'], values)
        result_text = json.dumps(plain(result))[:1000]
        return f"{arg['method']} returned {result_text}. Its effects were not independently verified."


class DesktopSettings:
    def __init__(self, commands, bus, executor):
        self.commands, self.bus, self.executor = commands, bus, executor

    async def command(self, key, *args):
        proc = await asyncio.create_subprocess_exec(self.commands[key], *args,
            env={**os.environ, 'LC_ALL': 'C'}, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            async with asyncio.timeout(12):
                out = await proc.stdout.read(65537)
                if len(out) > 65536:
                    raise ValueError('Desktop command output is too large')
                await proc.wait()
            if proc.returncode:
                raise RuntimeError(f'{key} failed')
            return out.decode(errors='replace').strip()
        except BaseException:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            raise

    async def themes(self, colors=False):
        output = await self.command('plasma-colors' if colors else 'plasma-theme', '--list-schemes' if colors else '--list')
        if colors:
            return [line.strip()[2:].removesuffix(' (current color scheme)') for line in output.splitlines() if line.strip().startswith('* ')]
        return [line.strip() for line in output.splitlines() if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]+', line.strip())]

    async def read(self, action):
        if action.name.startswith('dbus_'):
            return await self.bus.read(action)
        if action.argument == 'audio':
            return {'speakers': await self.command('wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@'),
                    'microphone': await self.command('wpctl', 'get-volume', '@DEFAULT_AUDIO_SOURCE@')}
        if action.argument == 'media':
            return await self.command('playerctl', 'status')
        return await self.themes(colors=action.argument == 'colors')

    async def current_theme(self, colors):
        return await self.command('kreadconfig', '--file', 'kdeglobals', '--group', 'General' if colors else 'KDE',
                                  '--key', 'ColorScheme' if colors else 'LookAndFeelPackage')

    async def prepare(self, action):
        if action.name in {'dbus_set', 'dbus_call'}:
            return await self.bus.prepare(action)
        prepared = {'action': asdict(action), 'requires_approval': action.name in {'dbus'}}
        if action.name == 'dbus':
            prepared['configured_call'] = self.executor.dbus_actions.registry[action.argument]
        if action.name in {'theme', 'color_scheme'}:
            colors = action.name == 'color_scheme'
            if action.argument not in await self.themes(colors):
                raise ValueError('Theme is not installed; list available themes first')
            prepared['before'] = await self.current_theme(colors)
            prepared['after'] = action.argument
        if action.name in {'microphone_mute', 'mute', 'volume'}:
            prepared['before'] = await self.command('wpctl', 'get-volume',
                '@DEFAULT_AUDIO_SOURCE@' if action.name == 'microphone_mute' else '@DEFAULT_AUDIO_SINK@')
        return prepared

    async def execute(self, prepared):
        from .actions import Action
        action = Action(**prepared['action'])
        if action.name in {'dbus_set', 'dbus_call'}:
            return await self.bus.execute(prepared)
        if action.name in {'theme', 'color_scheme'}:
            colors = action.name == 'color_scheme'
            if await self.current_theme(colors) != prepared['before']:
                raise RuntimeError('Theme changed since review')
            if colors:
                await self.command('plasma-colors', action.argument)
            else:
                await self.command('plasma-theme', '--apply', action.argument)
            if await self.current_theme(colors) != action.argument:
                raise RuntimeError('Theme readback did not match the request')
            return f'Applied {action.argument}.'
        if action.name in {'microphone_mute', 'mute'}:
            target = '@DEFAULT_AUDIO_SOURCE@' if action.name == 'microphone_mute' else '@DEFAULT_AUDIO_SINK@'
            await self.command('wpctl', 'set-mute', target, str(int(action.argument)))
            actual = await self.command('wpctl', 'get-volume', target)
            if ('[MUTED]' in actual) != action.argument:
                raise RuntimeError('Mute state could not be verified')
            device = 'Microphone' if action.name == 'microphone_mute' else 'Speakers'
            return f'{device} {"muted" if action.argument else "unmuted"}.'
        if action.name == 'volume':
            await self.command('wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', f'{action.argument}%')
            actual = await self.command('wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@')
            match = re.search(r'Volume: ([0-9.]+)', actual)
            if not match or abs(float(match[1]) * 100 - action.argument) > 1.1:
                raise RuntimeError('Volume readback did not match')
            return f'Volume set to {action.argument} percent.'
        if action.name == 'media':
            await self.command('playerctl', action.argument)
            status = await self.command('playerctl', 'status')
            if action.argument in {'pause', 'play'} and status.lower() != {'pause': 'paused', 'play': 'playing'}[action.argument]:
                raise RuntimeError('Playback state did not match')
            return f'Media command completed. Playback is {status.lower()}.'
        return await self.executor.execute(action)
