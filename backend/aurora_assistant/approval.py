"""Local, same-UID approval control. Grants are one-use and expire."""
import argparse
import asyncio
import copy
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import struct


def socket_path():
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime:
        raise ValueError('XDG_RUNTIME_DIR is required for the approval control')
    return Path(runtime) / 'aurora-assistant' / 'control.sock'


class Approval:
    def __init__(self):
        self.pending = None
        self.latest_search = None
        self.future = None
        self.server = None
        self.path = None

    async def start(self):
        self.path = socket_path()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.parent.stat().st_uid != os.getuid():
            raise ValueError('Approval directory is not owned by the current user')
        self.path.parent.chmod(0o700)
        if self.path.exists():
            if not stat.S_ISSOCK(self.path.lstat().st_mode):
                raise ValueError('Approval socket path is occupied by another file')
            # Do not steal an active controller socket.
            probe = socket.socket(socket.AF_UNIX)
            try:
                probe.connect(str(self.path))
            except ConnectionRefusedError:
                self.path.unlink()
            else:
                raise ValueError('An assistant control server is already running')
            finally:
                probe.close()
        self.server = await asyncio.start_unix_server(self._client, path=str(self.path), limit=8192)
        self.path.chmod(0o600)

    def dispatch(self, request):
        if request == {'command': 'sources'}:
            return {'search': copy.deepcopy(self.latest_search)}
        if request == {'command': 'pending'}:
            return {'pending': copy.deepcopy(self.pending)}
        if (type(request) is not dict or set(request) != {'command', 'id'}
                or request['command'] not in {'approve', 'deny'}):
            raise ValueError('Invalid approval command')
        if not self.pending or request['id'] != self.pending['id'] or self.future.done():
            raise ValueError('Approval is absent, expired, or already used')
        approved = request['command'] == 'approve'
        self.future.set_result(approved)
        self.pending = None
        return {'accepted': approved}

    async def _client(self, reader, writer):
        try:
            peer = writer.get_extra_info('socket')
            _, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != os.getuid():
                raise PermissionError('Approval requires the same desktop account')
            async with asyncio.timeout(5):
                data = await reader.readline()
            result = self.dispatch(json.loads(data))
        except Exception as exc:
            result = {'error': str(exc)}
        try:
            writer.write(json.dumps(result).encode() + b'\n')
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def request(self, detail, notify, timeout=120):
        if self.pending:
            raise RuntimeError('Another approval is pending')
        self.future = asyncio.get_running_loop().create_future()
        self.pending = {'id': secrets.token_hex(16), **copy.deepcopy(detail)}
        try:
            await notify('This change needs approval in the local approval control.')
            return await asyncio.wait_for(self.future, timeout)
        except asyncio.TimeoutError:
            return False
        finally:
            self.pending = None
            if not self.future.done():
                self.future.cancel()

    async def close(self):
        if self.future and not self.future.done():
            self.future.set_result(False)
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['pending', 'sources', 'approve', 'deny'])
    parser.add_argument('id', nargs='?')
    args = parser.parse_args()
    if args.command in {'approve', 'deny'} and not args.id:
        parser.error('approve and deny require the exact id shown by pending')
    request = {'command': args.command}
    if args.command in {'approve', 'deny'}:
        request['id'] = args.id
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(5)
        connection.connect(str(socket_path()))
        connection.sendall(json.dumps(request).encode() + b'\n')
        chunks = bytearray()
        while not chunks.endswith(b'\n'):
            data = connection.recv(8192)
            if not data:
                break
            chunks.extend(data)
            if len(chunks) > 262144:
                raise SystemExit('Approval response too large')
    result = json.loads(chunks)
    print(json.dumps(result, indent=2))
    if 'error' in result:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
