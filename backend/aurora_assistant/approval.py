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
from .telemetry import event, phase, snapshot


def socket_path():
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if not runtime:
        raise ValueError('XDG_RUNTIME_DIR is required for the approval control')
    return Path(runtime) / 'aurora-assistant' / 'control.sock'


class Approval:
    def __init__(self):
        self.catalog = None
        self.pending = None
        self.latest_search = None
        self.future = None
        self.server = None
        self.path = None
        self.request_active = False
        self.expiry_handle = None

    async def start(self):
        self.path = socket_path()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or self.path.parent.stat().st_uid != os.getuid():
            raise ValueError('Approval directory is not owned by the current user')
        self.path.parent.chmod(0o700)
        if self.path.exists():
            if not stat.S_ISSOCK(self.path.lstat().st_mode):
                raise ValueError('Approval socket path is occupied by another file')
            # Do not steal an active controller socket.
            probe = socket.socket(socket.AF_UNIX)
            probe.settimeout(1)
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
        if request == {'command': 'diagnostics'}:
            return snapshot()
        if request == {'command': 'catalog-status'}:
            return self.catalog.status() if self.catalog else {'live_documents': 0, 'enrichment_enabled': False}
        if request == {'command': 'capability-records'}:
            documents = []
            observed = self.catalog.documents() if self.catalog else []
            for document in observed[:256]:
                candidate = documents + [document]
                if len(json.dumps(candidate).encode()) > 131072:
                    break
                documents = candidate
            return {'documents': documents, 'truncated': len(documents) < len(observed)}
        if request == {'command': 'capabilities'}:
            return {'documentation': self.catalog.markdown() if self.catalog else 'No capabilities observed.'}
        if request == {'command': 'sources'}:
            return {'search': copy.deepcopy(self.latest_search)}
        if request == {'command': 'pending'}:
            return {'pending': copy.deepcopy(self.pending)}
        if (type(request) is not dict or set(request) != {'command', 'id'}
                or type(request['command']) is not str or request['command'] not in {'approve', 'deny'}):
            raise ValueError('Invalid approval command')
        if not self.pending or request['id'] != self.pending['id'] or self.future.done():
            raise ValueError('Approval is absent, expired, or already used')
        approved = request['command'] == 'approve'
        event("approval.decision", approved=approved)
        self.future.set_result(approved)
        self.pending = None
        return {'accepted': approved}

    async def _client(self, reader, writer):
        try:
            async with asyncio.timeout(5):
                try:
                    peer = writer.get_extra_info('socket')
                    _, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if uid != os.getuid():
                        raise PermissionError('Approval requires the same desktop account')
                    data = await reader.readline()
                    result = self.dispatch(json.loads(data))
                except Exception as exc:
                    result = {'error': str(exc)}
                writer.write(json.dumps(result).encode() + b'\n')
                await writer.drain()
        except (TimeoutError, ConnectionError, OSError):
            pass
        finally:
            writer.close()
            try:
                async with asyncio.timeout(1):
                    await writer.wait_closed()
            except (TimeoutError, ConnectionError, OSError):
                pass

    def stage(self, detail, timeout=120):
        """Expose one exact pending plan for either spoken or local CLI consent."""
        if self.request_active:
            raise RuntimeError('Another approval is pending')
        self.pending = {**copy.deepcopy(detail), 'id': secrets.token_hex(16)}
        self.request_active = True
        self.future = asyncio.get_running_loop().create_future()
        def expire():
            if self.future and not self.future.done():
                self.future.set_result(False)
                self.pending = None
                event('approval.expired')
        self.expiry_handle = asyncio.get_running_loop().call_later(max(0, timeout), expire)
        event('approval.pending', timeout_seconds=timeout)
        return self.pending['id'], self.future

    def clear(self):
        if self.expiry_handle:
            self.expiry_handle.cancel()
            self.expiry_handle = None
        if self.future and not self.future.done():
            self.future.cancel()
        self.pending = None
        self.request_active = False

    async def request(self, detail, notify, timeout=120):
        _, future = self.stage(detail, timeout)
        try:
            async with asyncio.timeout(timeout):
                await notify('This change needs approval in the local approval control.')
                return await future
        except TimeoutError:
            return False
        finally:
            self.clear()

    async def close(self):
        if self.expiry_handle:
            self.expiry_handle.cancel()
        if self.future and not self.future.done():
            self.future.set_result(False)
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.path.unlink(missing_ok=True)


def control_request(request):
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
    return json.loads(chunks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['pending', 'sources', 'capabilities', 'capability-records', 'catalog-status', 'diagnostics', 'approve', 'deny'])
    parser.add_argument('id', nargs='?')
    args = parser.parse_args()
    if args.command in {'approve', 'deny'} and not args.id:
        parser.error('approve and deny require the exact id shown by pending')
    request = {'command': args.command}
    if args.command in {'approve', 'deny'}:
        request['id'] = args.id
    try:
        result = control_request(request)
    except (FileNotFoundError, ConnectionRefusedError):
        raise SystemExit('Aurora control is unavailable: the controller is stopped or has not created its socket. '
                         'From the configured Plasma account, run: systemctl --user restart aurora-assistant.target. '
                         'Then inspect: systemctl --user status aurora-controller.service') from None
    except PermissionError:
        raise SystemExit('Aurora control access was denied. Run this command as the configured Plasma user, without sudo.') from None
    except (OSError, ValueError) as exc:
        raise SystemExit('Aurora control request failed (' + type(exc).__name__ + '). '
                         'Run aurora-report --since "30 minutes ago" for service details.') from None
    print(result['documentation'] if args.command == 'capabilities' and 'documentation' in result else json.dumps(result, indent=2))
    if 'error' in result:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
