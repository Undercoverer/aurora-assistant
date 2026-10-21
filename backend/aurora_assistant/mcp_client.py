"""Local stdio MCP transport and exact, single-use action consent.

This module never grants approval from model output. The controller explicitly
authorizes the prepared plan after human approval. Tokens remain per action;
there is no transaction and no mutation retry.
"""
import asyncio
import copy
import hashlib
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from .telemetry import event, phase, turn_id

MAX_JSON = 16384


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def strict_json(text):
    if type(text) is not str or len(text.encode()) > MAX_JSON:
        raise ValueError('MCP JSON exceeds limit')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Non-finite JSON value')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


class MCPFailure(RuntimeError):
    """Stable metadata-only failure; remote error bodies are never exposed."""


class Consent:
    def __init__(self, second_prompt, clock=time.monotonic):
        self.clock, self.second_prompt = clock, second_prompt
        self.pending = {}
        self.authorized = set()
        self.active = None

    def prepare(self, plan, request):
        now = self.clock()
        self.pending = {k: v for k, v in self.pending.items() if v[0]['expires_at'] > now}
        self.authorized.intersection_update(self.pending)
        if len(self.pending) >= 64:
            raise MCPFailure('mcp.pending_limit')
        token = secrets.token_hex(16)
        plan = copy.deepcopy({**plan, 'mcp_token': token, 'expires_at': now + 120})
        self.pending[token] = (plan, copy.deepcopy({**request, 'expires_at': now + 120}))
        return copy.deepcopy(plan)

    def authorize(self, plans):
        if not 1 <= len(plans) <= 4:
            raise MCPFailure('mcp.invalid_plan')
        selected = []
        for plan in plans:
            token = plan.get('mcp_token')
            if token is None:
                continue
            stored = self.pending.get(token)
            if (not stored or canonical(stored[0]) != canonical(plan)
                    or self.clock() >= stored[0]['expires_at'] or token in selected):
                raise MCPFailure('mcp.invalid_consent')
            selected.append(token)
        self.authorized.update(selected)

    def revoke(self, plans):
        for plan in plans:
            token = plan.get('mcp_token')
            self.authorized.discard(token)
            self.pending.pop(token, None)

    def begin(self, plan):
        if self.active is not None:
            raise MCPFailure('mcp.busy')
        token = plan.get('mcp_token')
        stored = self.pending.pop(token, None)
        approved = token in self.authorized
        self.authorized.discard(token)
        if (not approved or not stored or canonical(stored[0]) != canonical(plan)
                or self.clock() >= stored[0]['expires_at']):
            raise MCPFailure('mcp.invalid_consent')
        request = {**stored[1], 'confirmation_id': secrets.token_hex(16)}
        self.active = {'request': request, 'expires': stored[0]['expires_at'], 'used': False, 'accepted': False}
        return copy.deepcopy(request)

    async def elicit(self, message):
        active = self.active
        if active is None or active['used'] or self.clock() >= active['expires']:
            return False
        try:
            incoming = strict_json(message)
            if canonical(incoming) != canonical(active['request']):
                return False
        except (ValueError, TypeError, RecursionError):
            return False
        # Consume before awaiting a second prompt, preventing concurrent replay.
        active['used'] = True
        if incoming['bus'] == 'system':
            if self.second_prompt is None:
                return False
            try:
                async with asyncio.timeout(min(55, active['expires'] - self.clock())):
                    accepted = await self.second_prompt(copy.deepcopy(incoming))
            except Exception:
                return False
            if accepted is not True:
                return False
        active['accepted'] = self.active is active and self.clock() < active['expires']
        return active['accepted']

    def finish(self):
        self.active = None


class MCPTransport:
    def __init__(self, executable, consent):
        if type(executable) is not str or not os.path.isabs(executable):
            raise ValueError('MCP executable must be an absolute installed path')
        self.executable, self.consent = executable, consent
        self.session = None

    async def elicitation(self, context, params):
        from mcp.types import ElicitResult
        # URL elicitations and all unsolicited forms are denied.
        schema = getattr(params, 'requestedSchema', {})
        valid = (type(schema) is dict and schema.get('type') == 'object'
                 and schema.get('required') == ['confirm']
                 and schema.get('additionalProperties') is False
                 and type(schema.get('properties')) is dict
                 and set(schema['properties']) == {'confirm'}
                 and schema['properties']['confirm'].get('type') == 'boolean')
        accepted = (getattr(params, 'mode', 'form') == 'form' and valid
                    and await self.consent.elicit(params.message))
        return ElicitResult(action='accept' if accepted else 'decline',
                            content={'confirm': True} if accepted else None)

    @asynccontextmanager
    async def connect(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        env = {k: os.environ[k] for k in ('DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR') if k in os.environ}
        parameters = StdioServerParameters(command=self.executable, env=env)
        # Keep SDK cancel scopes in the same task that enters/exits this context.
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write, elicitation_callback=self.elicitation,
                                     read_timeout_seconds=timedelta(seconds=75)) as session:
                self.session = session
                try:
                    async with asyncio.timeout(10):
                        await session.initialize()
                        listed = await session.list_tools()
                        if {t.name for t in listed.tools} != {'describe_object', 'call_method', 'set_property'}:
                            raise MCPFailure('mcp.contract_mismatch')
                    event('mcp.connected')
                    yield self
                finally:
                    self.consent.finish()
                    self.consent.pending.clear()
                    self.consent.authorized.clear()
                    self.session = None

    async def call(self, tool, arguments):
        if self.session is None:
            raise MCPFailure('mcp.unavailable')
        with phase('mcp.client.call', tool=tool):
            try:
                async with asyncio.timeout(75):
                    result = await self.session.call_tool(tool, arguments, meta={'aurora_turn': turn_id.get()})
                if result.isError:
                    known = {'owner_mismatch', 'schema_changed', 'property_changed', 'readback_mismatch',
                             'confirmation_denied', 'confirmation_unavailable', 'approval_expired',
                             'type_error', 'rate_limited'}
                    messages = [getattr(item, 'text', None) for item in result.content]
                    reason = messages[0] if len(messages) == 1 and messages[0] in known else 'refused'
                    event('mcp.client.refused', tool=tool, reason=reason)
                    raise MCPFailure('mcp.' + reason)
                value = result.structuredContent
                if type(value) is not dict or len(canonical(value).encode()) > 262144:
                    raise MCPFailure('mcp.invalid_response')
                return value
            except asyncio.CancelledError:
                event('mcp.client.cancelled', tool=tool)
                raise
            except MCPFailure:
                raise
            except Exception:
                raise MCPFailure('mcp.transport_failed') from None


def request_digest(request):
    return hashlib.sha256(canonical(request).encode()).hexdigest()
