"""Strict MCP entry point for mcdbus 2026.3.6.3.

Only these tools are registered. Upstream interaction/shortcut tools are not
imported: their caller-supplied signatures and confirmation fallback bypass
this contract. Aurora's plan approval remains a separate requirement.
"""
import asyncio
from contextlib import asynccontextmanager
import hashlib
from collections import deque
from functools import wraps
import logging
import sys
import uuid
import json
import math
from time import monotonic
from xml.etree import ElementTree
from xml.parsers import expat

from dbus_fast import Message, MessageType, Variant
from dbus_fast.signature import SignatureTree
from dbus_fast.validators import is_bus_name_valid, is_interface_name_valid, is_object_path_valid
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation
from pydantic import BaseModel, ConfigDict, StrictBool
from mcdbus._bus import BusManager, serialize_variant

MAX_XML = 131072
MAX_ARGS = 16384
CALL_TIMEOUT = 8
CONFIRM_TIMEOUT = 60


class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirm: StrictBool


@asynccontextmanager
async def lifespan(server):
    manager = BusManager()
    try:
        yield manager
    finally:
        await manager.disconnect_all()


mcp = FastMCP('Aurora mcdbus', lifespan=lifespan, mask_error_details=True, strict_input_validation=True)



_inflight = asyncio.Semaphore(4)
_starts = deque()


def measured(fn):
    """Bound concurrent work and request rate; emit metadata-only call events."""
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        start = monotonic()
        while _starts and _starts[0] <= start - 60:
            _starts.popleft()
        if _inflight.locked() or len(_starts) >= 120:
            raise ToolError('rate_limited')
        _starts.append(start)
        outcome = 'success'
        identity = uuid.uuid4().hex[:12]
        ctx = kwargs.get('ctx')
        meta = getattr(getattr(getattr(ctx, 'request_context', None), 'meta', None), 'aurora_turn', None)
        turn = meta if type(meta) is str and len(meta) == 12 and all(c in '0123456789abcdef' for c in meta) else None
        try:
            async with _inflight:
                return await fn(*args, **kwargs)
        except asyncio.CancelledError:
            outcome = 'cancelled'
            raise
        except Exception as exc:
            reason = str(exc) if isinstance(exc, ToolError) else ''
            outcome = 'type_error' if reason == 'type_error' else 'refused' if reason in {
                'owner_mismatch', 'schema_changed', 'property_changed',
                'confirmation_denied', 'confirmation_unavailable'} else 'error'
            raise
        finally:
            print(json.dumps({'event': 'mcp.call.duration', 'call': identity,
                'turn': turn, 'tool': fn.__name__, 'value': round((monotonic() - start) * 1000, 3),
                'unit': 'ms'}), file=sys.stderr)
            print(json.dumps({'event': 'mcp.call.outcome', 'call': identity,
                'turn': turn, 'tool': fn.__name__, 'outcome': outcome}), file=sys.stderr)
    return wrapped


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def endpoint(bus, service, object_path):
    if bus not in ('session', 'system') or not is_bus_name_valid(service) or service.startswith(':'):
        raise ToolError('Invalid bus or well-known service name')
    if not is_object_path_valid(object_path):
        raise ToolError('Invalid object path')


async def send(connection, destination, path, interface, member, signature='', body=None):
    # No raw arguments or reply/error bodies in logs or public error messages.
    try:
        async with asyncio.timeout(CALL_TIMEOUT):
            reply = await connection.call(Message(destination=destination, path=path,
                interface=interface, member=member, signature=signature, body=body or []))
        if reply is None or reply.message_type != MessageType.METHOD_RETURN:
            raise ToolError('D-Bus call rejected')
        return reply.body
    except (TimeoutError, EOFError, OSError) as exc:
        raise ToolError('D-Bus call unavailable or timed out') from None


async def owner(connection, service):
    result = await send(connection, 'org.freedesktop.DBus', '/org/freedesktop/DBus',
                        'org.freedesktop.DBus', 'GetNameOwner', 's', [service])
    if len(result) != 1 or not isinstance(result[0], str) or not result[0].startswith(':'):
        raise ToolError('No unique service owner')
    return result[0]


async def describe(ctx, bus, service, object_path, expected_owner=None):
    endpoint(bus, service, object_path)
    connection = await ctx.lifespan_context.get_bus(bus)
    unique = await owner(connection, service)
    if expected_owner is not None and unique != expected_owner:
        raise ToolError('owner_mismatch')
    values = await send(connection, unique, object_path, 'org.freedesktop.DBus.Introspectable', 'Introspect')
    if len(values) != 1 or type(values[0]) is not str or len(values[0].encode()) > MAX_XML:
        raise ToolError('Invalid or oversized introspection')
    xml = values[0]
    node = parse_introspection(xml)
    return connection, unique, node, xml


def parse_introspection(xml):
    """Accept the inert standard D-Bus DOCTYPE, never a custom DTD.

    Validate declarations with Expat before ElementTree sees the document.
    No external parser or resource resolver is installed. Reject internal
    subsets before any entity declaration or expansion can be processed.
    """
    if type(xml) is not str or len(xml.encode()) > MAX_XML:
        raise ToolError('Invalid or oversized introspection')
    def reject(*args):
        raise ToolError('DTD and entity declarations are unsupported')
    def doctype(name, system_id, public_id, internal_subset):
        if (internal_subset or name != 'node'
                or public_id != '-//freedesktop//DTD D-BUS Object Introspection 1.0//EN'
                or system_id != 'http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd'):
            reject()
    parser = expat.ParserCreate()
    parser.StartDoctypeDeclHandler = doctype
    parser.EntityDeclHandler = reject
    parser.ExternalEntityRefHandler = reject
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(xml, True)
        node = ElementTree.fromstring(xml)
    except (expat.ExpatError, ElementTree.ParseError):
        raise ToolError('Invalid introspection XML') from None
    if node.tag != 'node':
        raise ToolError('Invalid introspection root')
    return node


def parse_json(text):
    if len(text.encode()) > MAX_ARGS:
        raise ToolError('Arguments exceed size limit')
    def reject_constant(value):
        raise ValueError('Non-finite number')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate key')
            result[key] = value
        return result
    try:
        return json.loads(text, parse_constant=reject_constant, object_pairs_hook=pairs)
    except (ValueError, RecursionError) as exc:
        raise ToolError('Invalid argument JSON') from None


def typed(signature, value):
    """Convert nested JSON containers, then let dbus-fast verify the wire type."""
    def convert(t, v):
        token = t.token
        if token == 'h':
            raise ValueError('File descriptors are unsupported')
        if token == 'v':
            if type(v) is not dict or set(v) != {'signature', 'value'}:
                raise ValueError('Variants require an explicit type and value')
            return Variant(v['signature'], typed(v['signature'], v['value']))
        if token == 'a':
            child = t.children[0]
            if child.token == '{':
                if type(v) is not dict or child.children[0].token != 's':
                    raise ValueError('Only string-keyed JSON dictionaries are supported')
                return {k: convert(child.children[1], val) for k, val in v.items()}
            if type(v) is not list:
                raise ValueError('Array must be a JSON list')
            converted = [convert(child, item) for item in v]
            return bytes(converted) if child.token == 'y' else converted
        if token == '(':
            if type(v) is not list or len(v) != len(t.children):
                raise ValueError('Invalid struct')
            return [convert(child, item) for child, item in zip(t.children, v)]
        if token in 'ynqiuxt' and type(v) is not int:
            raise ValueError('Integer required')
        if token == 'b' and type(v) is not bool:
            raise ValueError('Boolean required')
        if token == 'd' and (type(v) not in (int, float) or not math.isfinite(v)):
            raise ValueError('Finite number required')
        return v
    try:
        tree = SignatureTree(signature)
        if len(tree.types) != 1:
            raise ValueError('One complete type required')
        value = convert(tree.types[0], value)
        tree.verify([value])
        return value
    except Exception as exc:
        raise ToolError('type_error') from None


def member(node, interface, kind, name):
    if not is_interface_name_valid(interface):
        raise ToolError('Invalid interface')
    matches = [item for iface in node.findall('interface') if iface.get('name') == interface
               for item in iface.findall(kind) if item.get('name') == name]
    if len(matches) != 1:
        raise ToolError('Member absent or ambiguous')
    return matches[0]


async def confirm(ctx, request):
    # Every mutation is confirmed. No environment variable can enable fallback.
    try:
        async with asyncio.timeout(CONFIRM_TIMEOUT):
            result = await ctx.elicit(canonical(request), Confirmation)
    except Exception as exc:
        raise ToolError('confirmation_unavailable') from None
    if not isinstance(result, AcceptedElicitation) or not isinstance(result.data, Confirmation) or result.data.confirm is not True:
        raise ToolError('confirmation_denied')


def check_expiry(expires_at):
    if expires_at and (not math.isfinite(expires_at) or monotonic() >= expires_at):
        raise ToolError('approval_expired')


def correlate(request, confirmation_id, expires_at):
    check_expiry(expires_at)
    if expires_at:
        request['expires_at'] = expires_at
    if confirmation_id:
        if len(confirmation_id) != 32 or any(c not in '0123456789abcdef' for c in confirmation_id):
            raise ToolError('Invalid confirmation identifier')
        request['confirmation_id'] = confirmation_id


async def recheck(connection, service, unique):
    if await owner(connection, service) != unique:
        raise ToolError('owner_mismatch')
    # Invocation also uses unique, so a replacement cannot receive the call
    # even if ownership changes immediately after this check.


@mcp.tool()
@measured
async def describe_object(bus: str, service: str, object_path: str, ctx: Context) -> dict:
    """Return bounded raw XML and the unique owner used to obtain it."""
    _, unique, _, xml = await describe(ctx, bus, service, object_path)
    return {'owner': unique, 'xml': xml, 'contract': 'aurora-mcdbus-1'}


@mcp.tool()
@measured
async def call_method(bus: str, service: str, object_path: str, interface: str,
                      method: str, expected_owner: str, ctx: Context, args: str = '[]', confirmation_id: str = '', expires_at: float = 0) -> dict:
    """Call an introspected method. Caller-supplied signatures are not accepted."""
    connection, unique, node, _ = await describe(ctx, bus, service, object_path, expected_owner)
    selected = member(node, interface, 'method', method)
    inputs = [a for a in selected.findall('arg') if a.get('direction', 'in') == 'in']
    values = parse_json(args)
    if type(values) is not list or len(values) != len(inputs):
        raise ToolError('type_error')
    types = [a.get('type', '') for a in inputs]
    body = [typed(t, v) for t, v in zip(types, values)]
    request = {'contract': 'aurora-mcdbus-1', 'bus': bus, 'service': service,
               'owner': unique, 'object_path': object_path, 'interface': interface,
               'method': method, 'args': values, 'signature': ''.join(types)}
    correlate(request, confirmation_id, expires_at)
    await confirm(ctx, request)
    await recheck(connection, service, unique)
    # Check the selected signature again after user interaction, against the same owner.
    _, _, current, _ = await describe(ctx, bus, service, object_path, unique)
    if ElementTree.tostring(member(current, interface, 'method', method)) != ElementTree.tostring(selected):
        raise ToolError('schema_changed')
    check_expiry(expires_at)
    result = await send(connection, unique, object_path, interface, method, ''.join(types), body)
    return {'body': serialize_variant(result), 'request_digest': digest(request)}


@mcp.tool()
@measured
async def set_property(bus: str, service: str, object_path: str, interface: str,
                       property_name: str, value: str, expected_owner: str,
                       expected_value: str, ctx: Context, confirmation_id: str = '', expires_at: float = 0) -> dict:
    """Set a readable/writable introspected property with precondition and readback."""
    connection, unique, node, _ = await describe(ctx, bus, service, object_path, expected_owner)
    prop = member(node, interface, 'property', property_name)
    if prop.get('access') != 'readwrite':
        raise ToolError('Property must be readable and writable')
    signature = prop.get('type', '')
    parsed = parse_json(value)
    converted = typed(signature, parsed)
    before = parse_json(expected_value)
    request = {'contract': 'aurora-mcdbus-1', 'bus': bus, 'service': service,
               'owner': unique, 'object_path': object_path, 'interface': interface,
               'property': property_name, 'value': parsed, 'before': before, 'signature': signature}
    correlate(request, confirmation_id, expires_at)
    await confirm(ctx, request)
    await recheck(connection, service, unique)
    _, _, current, _ = await describe(ctx, bus, service, object_path, unique)
    if ElementTree.tostring(member(current, interface, 'property', property_name)) != ElementTree.tostring(prop):
        raise ToolError('schema_changed')
    actual = await send(connection, unique, object_path, 'org.freedesktop.DBus.Properties', 'Get', 'ss', [interface, property_name])
    if canonical(serialize_variant(actual[0])) != canonical(before):
        raise ToolError('property_changed')
    check_expiry(expires_at)
    await send(connection, unique, object_path, 'org.freedesktop.DBus.Properties', 'Set', 'ssv',
               [interface, property_name, Variant(signature, converted)])
    actual = await send(connection, unique, object_path, 'org.freedesktop.DBus.Properties', 'Get', 'ss', [interface, property_name])
    if canonical(serialize_variant(actual[0])) != canonical(serialize_variant(converted)):
        raise ToolError('readback_mismatch')
    return {'value': serialize_variant(actual[0]), 'request_digest': digest(request)}


def main():
    # Framework validation failures may contain user values. Keep the explicit
    # metadata audit above; do not forward third-party exception logs.
    logging.getLogger('fastmcp').setLevel(logging.CRITICAL)
    mcp.run(transport='stdio', log_level='CRITICAL', show_banner=False)


if __name__ == '__main__':
    main()
