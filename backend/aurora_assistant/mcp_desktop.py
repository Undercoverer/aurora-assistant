"""Controller desktop transport: every action crosses the strict MCP boundary."""
import json
from .actions import Action
from .desktop_bus import NAME, PATH, INTERFACE
from .mcp_client import canonical, MCPFailure


class MCPDesktop:
    def __init__(self, bus, executor):
        self.bus, self.executor = bus, executor
        from .mcp_bus import MCPBusAccess
        self.adapter_bus = MCPBusAccess({'discoveryScope': 'restricted', 'sessionPrefixes': [NAME], 'systemPrefixes': []},
                                        bus.transport, bus.consent)
        self.observed_owner = None

    async def adapter(self, method, args, owner):
        result = await self.bus.transport.call('desktop_query', {
            'method': method, 'args': canonical(args), 'expected_owner': owner})
        if result.get('owner') != owner or type(result.get('body')) is not list or len(result['body']) != 1:
            raise MCPFailure('mcp.invalid_adapter_reply')
        raw = result['body'][0]
        if type(raw) is not str or len(raw.encode()) > 65536:
            raise MCPFailure('mcp.invalid_adapter_reply')
        return json.loads(raw)

    async def owner(self):
        return (await self.adapter_bus._description({'bus': 'session', 'destination': NAME, 'path': PATH}))['owner']

    async def describe(self):
        owner = await self.owner()
        value = await self.adapter('Describe', [], owner)
        self.observed_owner = owner
        return {'source': {'bus': 'session', 'destination': NAME, 'path': PATH,
                           'interface': INTERFACE, 'owner': owner}, 'description': value}

    async def read(self, action):
        if action.name.startswith('dbus_'):
            return await self.bus.read(action)
        return await self.adapter('Read', [action.argument], await self.owner())

    async def prepare(self, action):
        if action.name in {'dbus_set', 'dbus_call'}:
            return await self.bus.prepare(action)
        if action.name == 'dbus':
            item = self.executor.dbus_actions.registry[action.argument]
            generic = Action('dbus_call', {'bus': item.get('bus', 'session'),
                'destination': item['destination'], 'path': item['path'],
                'interface': item['interface'], 'method': item['member'],
                'argumentsJson': canonical(item.get('arguments', []))})
            prepared = await self.bus.prepare(generic)
            # Keep the configured reply check in the exact approved plan.
            self.bus.consent.revoke([prepared])
            request = self.bus.request_for(prepared, generic)
            if prepared['signature'] != item.get('signature', ''):
                raise ValueError('Configured signature differs from live introspection')
            prepared.update(configured_reply=item.get('expectedReply'))
            return self.bus.consent.prepare(prepared, request)
        owner = await self.owner()
        if self.observed_owner is not None and owner != self.observed_owner:
            raise RuntimeError('Desktop capabilities changed owner; refresh discovery')
        reply = await self.adapter('Prepare', [action.name, canonical(action.argument)], owner)
        if (type(reply) is not dict or type(reply.get('token')) is not str
                or type(reply.get('plan')) is not dict or type(reply.get('expires_at')) not in (int, float)):
            raise MCPFailure('mcp.invalid_adapter_plan')
        generic = Action('dbus_call', {'bus': 'session', 'destination': NAME, 'path': PATH,
            'interface': INTERFACE, 'method': 'Apply', 'argumentsJson': canonical([reply['token']])})
        prepared = await self.adapter_bus.prepare(generic)
        self.bus.consent.revoke([prepared])
        if prepared['owner'] != owner:
            raise MCPFailure('mcp.owner_mismatch')
        request = self.bus.request_for(prepared, generic)
        prepared.update(adapter_plan=reply['plan'], adapter_result=True,
                        expires_at=min(prepared['expires_at'], reply['expires_at']))
        return self.bus.consent.prepare(prepared, request)

    def apply_policy(self, prepared, effects):
        rebound = []
        try:
            if len(prepared) != len(effects):
                raise MCPFailure('mcp.invalid_consent')
            for plan, effect in zip(prepared, effects):
                rebound.append(self.bus.consent.apply_policy(plan, effect))
            return rebound
        except BaseException:
            self.bus.consent.revoke(prepared + rebound)
            raise

    def authorize_routine(self, prepared):
        self.bus.consent.authorize_routine(prepared)

    def authorize_plan(self, prepared, system_confirmed=False):
        self.bus.consent.authorize(prepared, system_confirmed=system_confirmed)

    def revoke_plan(self, prepared):
        self.bus.consent.revoke(prepared)

    async def execute(self, prepared):
        return await self.bus.execute(prepared)
