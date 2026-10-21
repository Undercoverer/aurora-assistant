"""Opt-in MCP execution for generic D-Bus calls; legacy reads remain available."""
import json
from .settings import BusAccess
from .mcp_client import MCPFailure, canonical, strict_json, request_digest


class MCPBusAccess(BusAccess):
    def __init__(self, config, transport, consent):
        super().__init__(config)
        self.transport, self.consent = transport, consent

    async def describe(self, arg):
        from dbus_next.introspection import Node
        if not self.allowed(arg['bus'], arg['destination']):
            raise ValueError('D-Bus service is outside configured discovery scope')
        value = await self.transport.call('describe_object', {
            'bus': arg['bus'], 'service': arg['destination'], 'object_path': arg['path']})
        if (value.get('contract') != 'aurora-mcdbus-1'
                or type(value.get('owner')) is not str or not value['owner'].startswith(':')
                or type(value.get('xml')) is not str or len(value['xml'].encode()) > 131072):
            raise MCPFailure('mcp.invalid_description')
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
        request = {'contract': 'aurora-mcdbus-1', 'bus': arg['bus'],
                   'service': arg['destination'], 'owner': prepared['owner'],
                   'object_path': arg['path'], 'interface': arg['interface'],
                   'signature': prepared['signature']}
        if action.name == 'dbus_set':
            request.update(property=arg['property'], value=parsed, before=prepared['before'])
        else:
            request.update(method=arg['method'], args=parsed)
        return self.consent.prepare(prepared, request)

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
            return f"{request['method']} returned {json.dumps(result.get('body'))[:1000]}. Its effects were not independently verified."
        finally:
            self.consent.finish()
