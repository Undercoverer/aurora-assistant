"""Strict MCP execution and live introspection for D-Bus calls."""
import json
from .settings import BusAccess
from .mcp_client import MCPFailure, canonical, strict_json, request_digest


class MCPBusAccess(BusAccess):
    def __init__(self, config, transport, consent):
        super().__init__({'sessionPrefixes': ['org.kde.', 'org.mpris.', 'org.example.VoiceOverlay', 'org.aurora.Desktop'], **config})
        self.transport, self.consent = transport, consent
        self.discovery_scope = config.get('discoveryScope', 'all')

    def allowed(self, bus, destination):
        if self.discovery_scope == 'all':
            return bus in ('session', 'system') and not destination.startswith(':')
        return super().allowed(bus, destination)

    async def call(self, *args, **kwargs):
        raise MCPFailure('mcp.direct_transport_disabled')

    async def read(self, action):
        if action.name == 'dbus_list':
            value = await self.transport.call('list_services', {'bus': action.argument})
            names = value.get('services')
            if type(names) is not list or len(names) > 512 or any(type(n) is not str for n in names):
                raise MCPFailure('mcp.invalid_description')
            permitted = [n for n in names if self.allowed(action.argument, n)]
            return {'services': permitted[:150],
                    'truncated': bool(value.get('truncated')) or len(permitted) > 150,
                    'scope': self.discovery_scope,
                    'note': 'Running services only. Omitted services and installed applications may still exist.'}
        if action.name == 'dbus_get':
            return await self.get(action.argument)
        return (await self._description(action.argument))['description']

    async def get(self, arg, owner=None):
        if owner is None:
            owner = (await self._description(arg))['owner']
        if not self.allowed(arg['bus'], arg['destination']):
            raise ValueError('D-Bus service is outside configured discovery scope')
        result = await self.transport.call('read_property', {
            'bus': arg['bus'], 'service': arg['destination'], 'object_path': arg['path'],
            'interface': arg['interface'], 'property_name': arg['property'], 'expected_owner': owner})
        if result.get('owner') != owner or 'value' not in result:
            raise MCPFailure('mcp.invalid_description')
        return result['value']

    async def _description(self, arg):
        if not self.allowed(arg['bus'], arg['destination']):
            raise ValueError('D-Bus service is outside configured discovery scope')
        value = await self.transport.call('describe_object', {
            'bus': arg['bus'], 'service': arg['destination'], 'object_path': arg['path']})
        if (value.get('contract') != 'aurora-mcdbus-1'
                or type(value.get('owner')) is not str or not value['owner'].startswith(':')
                or type(value.get('xml')) is not str or len(value['xml'].encode()) > 131072):
            raise MCPFailure('mcp.invalid_description')
        described = value.get('description')
        if (type(described) is not dict or described.get('owner') != value['owner']
                or type(described.get('interfaces')) is not list or len(described['interfaces']) > 32
                or type(described.get('children')) is not list or len(described['children']) > 32):
            raise MCPFailure('mcp.invalid_description')
        return value

    async def describe(self, arg):
        from dbus_next.introspection import Node
        value = await self._description(arg)
        # The pinned strict server has already rejected entity/DTD processing.
        # Also reject internal subsets at this client boundary before Node.parse.
        from xml.parsers import expat
        parser = expat.ParserCreate()
        def doctype(name, system, public, subset):
            if subset:
                raise MCPFailure('mcp.invalid_description')
        parser.StartDoctypeDeclHandler = doctype
        parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
        parser.Parse(value['xml'], True)
        return value['owner'], Node.parse(value['xml'])

    async def prepare(self, action):
        # Reject ambiguous JSON before the legacy preparation type checks.
        arg = action.argument
        key = 'valueJson' if action.name == 'dbus_set' else 'argumentsJson'
        parsed = strict_json(arg[key])
        prepared = await super().prepare(action)
        request = self.request_for(prepared, action)
        return self.consent.prepare(prepared, request)

    def request_for(self, prepared, action):
        arg = action.argument
        parsed = strict_json(arg['valueJson' if action.name == 'dbus_set' else 'argumentsJson'])
        request = {'contract': 'aurora-mcdbus-1', 'bus': arg['bus'],
                   'service': arg['destination'], 'owner': prepared['owner'],
                   'object_path': arg['path'], 'interface': arg['interface'],
                   'signature': prepared['signature']}
        if action.name == 'dbus_set':
            request.update(property=arg['property'], value=parsed, before=prepared['before'])
        else:
            request.update(method=arg['method'], args=parsed)
        return request

    async def execute(self, prepared):
        request = self.consent.begin(prepared)
        try:
            arguments = {'bus': request['bus'], 'service': request['service'],
                         'object_path': request['object_path'], 'interface': request['interface'],
                         'expected_owner': request['owner'], 'confirmation_id': request['confirmation_id'],
                         'expires_at': request['expires_at']}
            if 'method' in request:
                tool = 'call_method'
                arguments.update(method=request['method'], args=canonical(request['args']))
            else:
                tool = 'set_property'
                arguments.update(property_name=request['property'], value=canonical(request['value']),
                                 expected_value=canonical(request['before']))
            result = await self.transport.call(tool, arguments)
            if (not self.consent.active['accepted']
                    or result.get('request_digest') != request_digest(request)):
                raise MCPFailure('mcp.unverified_result')
            if tool == 'set_property':
                return f"{request['property']} readback is {json.dumps(result.get('value'))}."
            if prepared.get('configured_reply') is not None and canonical(result.get('body')) != canonical(prepared['configured_reply']):
                raise MCPFailure('mcp.unexpected_reply')
            if prepared.get('adapter_result'):
                body = result.get('body')
                if type(body) is not list or len(body) != 1 or type(body[0]) is not str:
                    raise MCPFailure('mcp.invalid_adapter_reply')
                return body[0]
            return f"{request['method']} returned {json.dumps(result.get('body'))[:1000]}. Its effects were not independently verified."
        finally:
            self.consent.finish()
