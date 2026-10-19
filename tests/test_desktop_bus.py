import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from dbus_next import DBusError, Variant
from dbus_next.service import ServiceInterface
from aurora_assistant.actions import Action
from aurora_assistant.desktop_bus import DesktopService, RemoteDesktop, applications
from aurora_assistant.native_media import NativeMedia


async def invoke(service, name, *args):
    method = next(m for m in ServiceInterface._get_methods(service) if m.name == name)
    return await method.fn(service, *args)


class DesktopTests(unittest.IsolatedAsyncioTestCase):
    async def test_tokens_are_single_use_and_unknown_actions_fail(self):
        service = DesktopService({'apps': {}, 'commands': {}})
        service.desktop.prepare = AsyncMock(return_value={'action': {'name': 'mute', 'argument': True}, 'requires_approval': False})
        service.desktop.execute = AsyncMock(return_value='Muted.')
        result = json.loads(await invoke(service, 'Prepare', 'mute', 'true'))
        self.assertEqual(await invoke(service, 'Apply', result['token']), 'Muted.')
        with self.assertRaises(DBusError):
            await invoke(service, 'Apply', result['token'])
        with self.assertRaises(DBusError):
            await invoke(service, 'Prepare', 'shell', '"ls"')
        service.desktop.execute.assert_awaited_once()

    async def test_expired_token_does_not_execute(self):
        service = DesktopService({'apps': {}, 'commands': {}})
        service.pending['old'] = (time.monotonic() - 1, {})
        service.desktop.execute = AsyncMock()
        with self.assertRaises(DBusError):
            await invoke(service, 'Apply', 'old')
        service.desktop.execute.assert_not_awaited()

    async def test_remote_restart_does_not_apply_token(self):
        bus = AsyncMock()
        remote = RemoteDesktop(bus, AsyncMock())
        remote.owner = AsyncMock(return_value=':1.9')
        with self.assertRaisesRegex(RuntimeError, 'restarted'):
            await remote.execute({'action': {'name': 'mute', 'argument': True}, 'desktop_owner': ':1.8', 'desktop_token': 'token'})
        bus.call.assert_not_awaited()

    async def test_launch_rejects_missing_application(self):
        service = DesktopService({'apps': {}, 'commands': {}})
        with patch('aurora_assistant.desktop_bus.applications', return_value={}):
            with self.assertRaises(DBusError):
                await invoke(service, 'Prepare', 'launch_app', '"missing.desktop"')

    def test_xdg_hidden_override_and_desktop_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            user, system = Path(tmp)/'user', Path(tmp)/'system'
            for root in [user, system]:
                (root/'applications').mkdir(parents=True)
            (system/'applications/a.desktop').write_text('[Desktop Entry]\nType=Application\nName=App\n')
            (user/'applications/a.desktop').write_text('[Desktop Entry]\nType=Application\nHidden=true\n')
            (system/'applications/b.desktop').write_text('[Desktop Entry]\nType=Application\nName=Visible\nOnlyShowIn=KDE;\n')
            (system/'applications/c.desktop').write_text('[Desktop Entry]\nType=Application\nName=Other\nOnlyShowIn=GNOME;\n')
            with patch.dict(os.environ, XDG_DATA_HOME=str(user), XDG_DATA_DIRS=str(system), XDG_CURRENT_DESKTOP='KDE'):
                self.assertEqual(applications(), {'b.desktop': 'Visible'})


class MediaTests(unittest.IsolatedAsyncioTestCase):
    def player(self, name, status='Playing'):
        return {'destination': name, 'owner': ':1.2', 'PlaybackStatus': status, 'CanControl': True,
                'CanPause': True, 'CanPlay': True, 'CanGoNext': True, 'CanGoPrevious': True}

    async def test_native_pause_and_readback(self):
        bus = AsyncMock()
        media = NativeMedia(bus)
        media.players = AsyncMock(return_value=[self.player('org.mpris.MediaPlayer2.test')])
        prepared = await media.prepare(Action('media', 'pause'))
        bus.call.side_effect = [[':1.2'], [], [Variant('s', 'Paused')]]
        self.assertEqual(await media.execute(prepared), 'Playback is paused.')
        self.assertEqual(bus.call.await_args_list[1].args[4], 'Pause')

    async def test_ambiguous_players_do_not_run(self):
        media = NativeMedia(AsyncMock())
        media.players = AsyncMock(return_value=[self.player('one'), self.player('two')])
        with self.assertRaisesRegex(ValueError, 'unique'):
            await media.prepare(Action('media', 'pause'))
        media.bus.call.assert_not_awaited()

    async def test_changed_toggle_does_not_run(self):
        bus = AsyncMock()
        media = NativeMedia(bus)
        media.players = AsyncMock(return_value=[self.player('org.mpris.MediaPlayer2.test')])
        prepared = await media.prepare(Action('media', 'play-pause'))
        bus.call.side_effect = [[':1.2'], [Variant('s', 'Paused')]]
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            await media.execute(prepared)
        self.assertEqual(bus.call.await_count, 2)

@unittest.skipUnless(os.environ.get('DBUS_SESSION_BUS_ADDRESS'), 'Needs a test session bus')
class DesktopIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_bus_prepare_apply_and_replay_rejection(self):
        from dbus_next.aio import MessageBus
        from aurora_assistant.desktop_bus import NAME, PATH
        from aurora_assistant.settings import BusAccess
        server = await MessageBus().connect()
        service = DesktopService({'apps': {}, 'commands': {}})
        service.desktop.prepare = AsyncMock(return_value={'action': {'name': 'mute', 'argument': True}, 'requires_approval': False})
        service.desktop.execute = AsyncMock(return_value='Muted.')
        server.export(PATH, service)
        await server.request_name(NAME)
        remote = RemoteDesktop(BusAccess({}), AsyncMock())
        try:
            prepared = await remote.prepare(Action('mute', True))
            self.assertEqual(await remote.execute(prepared), 'Muted.')
            with self.assertRaises(RuntimeError):
                await remote.execute(prepared)
            service.desktop.execute.assert_awaited_once()
        finally:
            server.disconnect()
