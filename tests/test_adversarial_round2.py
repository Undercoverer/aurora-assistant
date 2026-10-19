"""Fault injection for cleanup, review policy, discovery and approval races."""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from aurora_assistant.approval import Approval
from aurora_assistant.agent import SettingsAgent
from aurora_assistant.native_media import NativeMedia


class ApprovalRaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_request_cannot_replace_completed_but_unreturned_first(self):
        approval = Approval()
        release = asyncio.Event()
        entered = asyncio.Event()
        async def notify(_):
            entered.set()
            await release.wait()
        first = asyncio.create_task(approval.request({}, notify))
        await entered.wait()
        approval.dispatch({'command': 'approve', 'id': approval.pending['id']})
        try:
            with self.assertRaises(RuntimeError):
                await approval.request({}, AsyncMock(), timeout=.01)
        finally:
            release.set()
            self.assertTrue(await first)
        self.assertFalse(await approval.request({}, AsyncMock(), timeout=.01))

    async def test_cancelled_request_allows_new_request(self):
        approval = Approval()
        pending = asyncio.create_task(approval.request({}, AsyncMock()))
        await asyncio.sleep(0)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertIsNone(approval.pending)
        self.assertFalse(await approval.request({}, AsyncMock(), timeout=.01))


class MediaDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_unreadable_player_does_not_leave_partial_selection(self):
        bus = AsyncMock()
        bus.call.side_effect = [[['org.mpris.MediaPlayer2.one', 'org.mpris.MediaPlayer2.two']],
            [':1.1'], [{'PlaybackStatus': 'Playing', 'CanControl': True, 'CanPlay': True,
                        'CanPause': True, 'CanGoNext': True, 'CanGoPrevious': True}],
            [':1.2'], RuntimeError('unresponsive')]
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            await NativeMedia(bus).players()

    async def test_excess_players_are_not_silently_truncated(self):
        bus = AsyncMock()
        bus.call.return_value = [[f'org.mpris.MediaPlayer2.p{i}' for i in range(33)]]
        with self.assertRaisesRegex(ValueError, 'Too many'):
            await NativeMedia(bus).players()
        bus.call.assert_awaited_once()

    async def test_discovery_has_total_timeout(self):
        media = NativeMedia(AsyncMock())
        async def hang():
            await asyncio.Event().wait()
        media._players = hang
        real_timeout = asyncio.timeout
        with patch('aurora_assistant.native_media.asyncio.timeout', side_effect=lambda _: real_timeout(.01)):
            with self.assertRaises(TimeoutError):
                await media.players()


class PlanExpiryTests(unittest.IsolatedAsyncioTestCase):
    def agent(self, deadline):
        inference, desktop, approval, overlay = [AsyncMock() for _ in range(4)]
        inference.plan.return_value = {'actions': [{'name': 'mute', 'argument': True}], 'reply': ''}
        inference.review.return_value = {'decision': 'ask', 'reason': 'Review'}
        desktop.prepare.return_value = {'action': {'name': 'mute', 'argument': True},
            'requires_approval': True, 'expires_at': deadline}
        agent = SettingsAgent({'apps': {}}, inference, desktop, approval, overlay)
        return agent, desktop, approval

    async def test_expired_review_does_not_ask_or_execute(self):
        agent, desktop, approval = self.agent(time.monotonic() - 1)
        self.assertIn('expired', await agent.run('mute'))
        approval.request.assert_not_awaited()
        desktop.execute.assert_not_awaited()

    async def test_approval_timeout_fits_token_lifetime(self):
        agent, desktop, approval = self.agent(time.monotonic() + 20)
        approval.request.return_value = False
        await agent.run('mute')
        self.assertTrue(0 < approval.request.call_args.kwargs['timeout'] <= 18)
        desktop.execute.assert_not_awaited()

    async def test_expiry_after_approval_does_not_execute(self):
        agent, desktop, approval = self.agent(100)
        with patch('aurora_assistant.agent.time.monotonic', side_effect=[50, 50, 101]):
            self.assertIn('expired', await agent.run('mute'))
        desktop.execute.assert_not_awaited()

    async def test_disabled_discovery_rejects_settings_action(self):
        agent, desktop, approval = self.agent(time.monotonic() + 20)
        agent.config['settings'] = {'enable': False}
        agent.inference.plan.return_value = {'actions': [{'name': 'theme', 'argument': 'Breeze'}], 'reply': ''}
        with self.assertRaises(ValueError):
            await agent.run('theme')
        desktop.prepare.assert_not_awaited()


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, *, reset_fails=False, startup_fails=False, overlay_fails=False):
        from aurora_assistant import main
        overlay = AsyncMock()
        overlay.close = Mock()
        inference, approval = AsyncMock(), AsyncMock()
        controller = Mock()
        controller.handle = AsyncMock()
        async def visuals():
            await asyncio.Event().wait()
        controller.visuals = visuals
        if reset_fails:
            overlay.reset.side_effect = RuntimeError('reset failed')
        if startup_fails:
            inference.wait_ready.side_effect = RuntimeError('not ready')
        if overlay_fails:
            overlay.connect.side_effect = RuntimeError('no bus')
        with patch.object(main, 'Overlay', return_value=overlay), \
             patch.object(main, 'Inference', return_value=inference), \
             patch.object(main, 'Approval', return_value=approval), \
             patch.object(main, 'Controller', return_value=controller):
            config = {'apps': {}, 'commands': {}, 'settings': {'enable': False}}
            if reset_fails or startup_fails or overlay_fails:
                with self.assertRaises(RuntimeError):
                    await main.run(config, text='mute')
            else:
                await main.run(config, text='mute')
        overlay.close.assert_called_once()
        if not overlay_fails:
            inference.close.assert_awaited_once()
            approval.close.assert_awaited_once()
        return controller, approval

    async def test_reset_failure_still_closes_other_resources(self):
        await self.exercise(reset_fails=True)

    async def test_readiness_failure_closes_acquired_resources(self):
        await self.exercise(startup_fails=True)

    async def test_connect_failure_closes_overlay(self):
        await self.exercise(overlay_fails=True)

    async def test_disabled_discovery_still_uses_review_agent(self):
        controller, approval = await self.exercise()
        self.assertIsInstance(controller.agent, SettingsAgent)
        approval.start.assert_awaited_once()


class ApprovalClientTests(unittest.IsolatedAsyncioTestCase):
    def connection(self):
        import os
        import struct
        reader, writer = AsyncMock(), Mock()
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        writer.get_extra_info.return_value.getsockopt.return_value = struct.pack('3i', 1, os.getuid(), 1)
        return reader, writer

    async def test_cancellation_during_read_closes_writer(self):
        reader, writer = self.connection()
        entered = asyncio.Event()
        async def hang():
            entered.set()
            await asyncio.Event().wait()
        reader.readline.side_effect = hang
        task = asyncio.create_task(Approval()._client(reader, writer))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        writer.close.assert_called_once()
        writer.wait_closed.assert_awaited_once()

    async def test_client_not_reading_response_cannot_stall_drain(self):
        reader, writer = self.connection()
        reader.readline.return_value = b'{"command":"pending"}\n'
        async def hang():
            await asyncio.Event().wait()
        writer.drain.side_effect = hang
        real_timeout = asyncio.timeout
        with patch('aurora_assistant.approval.asyncio.timeout', side_effect=lambda _: real_timeout(.01)):
            await Approval()._client(reader, writer)
        writer.close.assert_called_once()


class VoiceShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_capture_closes_voice_and_other_resources(self):
        import threading
        from aurora_assistant import main
        entered, release = threading.Event(), threading.Event()
        voice = Mock()
        def capture():
            entered.set()
            release.wait(2)
            return ''
        voice.next.side_effect = capture
        voice.close.side_effect = release.set
        overlay, inference, approval = AsyncMock(), AsyncMock(), AsyncMock()
        overlay.close = Mock()
        with patch.object(main, 'Overlay', return_value=overlay), \
             patch.object(main, 'Inference', return_value=inference), \
             patch.object(main, 'Approval', return_value=approval), \
             patch('aurora_assistant.voice.Voice', return_value=voice):
            task = asyncio.create_task(main.run({'apps': {}, 'commands': {}, 'stt': {}}))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        voice.close.assert_called_once()
        inference.close.assert_awaited_once()
        approval.close.assert_awaited_once()
        overlay.close.assert_called_once()
