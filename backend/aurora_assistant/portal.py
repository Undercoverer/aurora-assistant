"""Open an HTTP(S) URL through the desktop portal, without shell commands."""
import asyncio
import secrets
from urllib.parse import urlsplit


def valid_url(value):
    if type(value) is not str or not 1 <= len(value) <= 2048 or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        url = urlsplit(value)
        return url.scheme in {'https', 'http'} and bool(url.hostname) and url.username is None and url.password is None and url.port != 0
    except ValueError:
        return False


async def open_url(url):
    from dbus_next import Message, MessageType, Variant
    from dbus_next.aio import MessageBus
    if not valid_url(url):
        raise ValueError('Only HTTP(S) browser URLs are supported')
    bus = await MessageBus().connect()
    future = asyncio.get_running_loop().create_future()
    early = []
    expected = None
    def response(message):
        if (message.message_type == MessageType.SIGNAL and message.interface == 'org.freedesktop.portal.Request'
                and message.member == 'Response'):
            if expected is None:
                if len(early) < 32:
                    early.append(message)
            elif (message.path, message.sender) == expected and not future.done():
                future.set_result(message.body)
    bus.add_message_handler(response)
    try:
        async with asyncio.timeout(30):
            match = "type='signal',interface='org.freedesktop.portal.Request',member='Response',path_namespace='/org/freedesktop/portal/desktop/request'"
            reply = await bus.call(Message(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
                interface='org.freedesktop.DBus', member='AddMatch', signature='s', body=[match]))
            if reply.message_type != MessageType.METHOD_RETURN:
                raise RuntimeError('Cannot subscribe to portal response')
            reply = await bus.call(Message(destination='org.freedesktop.portal.Desktop',
                path='/org/freedesktop/portal/desktop', interface='org.freedesktop.portal.OpenURI',
                member='OpenURI', signature='ssa{sv}', body=['', url, {'handle_token': Variant('s', 'aurora' + secrets.token_hex(8))}]))
            if reply.message_type != MessageType.METHOD_RETURN or not reply.body:
                raise RuntimeError('Browser portal rejected request')
            expected = (reply.body[0], reply.sender)
            for message in early:
                response(message)
            result = await future
            if not result or result[0] != 0:
                raise RuntimeError('Browser request was cancelled or failed')
            return 'The browser accepted the request to open the page.'
    finally:
        bus.remove_message_handler(response)
        bus.disconnect()
