import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch
from aurora_assistant.kev import Kev, common_plan
from aurora_assistant.controller import Controller
from aurora_assistant.portal import valid_url, open_url
from aurora_assistant import telemetry


class CandidateTests(unittest.TestCase):
    def test_volume_and_multiple_actions(self):
        self.assertEqual(common_plan('raise the volume to 12')['actions'], [{'name': 'volume', 'argument': 12}])
        self.assertEqual(len(common_plan('mute the microphone and pause playback')['actions']), 2)
        self.assertEqual(common_plan('open youtube')['actions'][0]['argument'], 'https://www.youtube.com/')

    def test_unknown_and_partial_requests_escalate(self):
        for text in ('Hope in youtube', 'raise the volume by 12', 'raise the volume to 200',
                     'mute the speakers and delete files', 'do not mute the speakers', 'set volume to -12'):
            with self.subTest(text=text):
                self.assertIsNone(common_plan(text))

    def test_browser_url_validation(self):
        self.assertTrue(valid_url('https://www.youtube.com/'))
        for value in ('file:///etc/passwd', 'javascript:alert(1)', 'https://user:pass@host.org',
                      'https://host.org:99999', 'https://host.org/\nhello', None):
            self.assertFalse(valid_url(value))


class DecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_probabilities_never_authorize(self):
        kev = Kev({}, AsyncMock())
        for value in (True, float('nan'), -1, 2):
            kev.decide = AsyncMock(return_value={'route': {'choice': 'apply', 'probabilities': {'apply': value, 'escalate': 0}}})
            with self.subTest(value=value), self.assertRaises(ValueError):
                await kev.route('mute the speakers')

    async def test_review_uses_noul_and_low_score_requires_approval(self):
        kev = Kev({}, AsyncMock())
        kev.decide = AsyncMock(return_value={'safe': {'noul': .4}})
        self.assertEqual((await kev.review('mute', []))['decision'], 'ask')
        self.assertEqual(kev.decide.call_args.args[1]['safe']['type'], 'noul')


class PresentationTests(unittest.IsolatedAsyncioTestCase):
    def controller(self):
        agent = Mock(failed=False, awaiting_reply=False)
        agent.run = AsyncMock(return_value='Done.')
        controller = Controller(AsyncMock(), AsyncMock(), AsyncMock(), {}, agent=agent,
            presentation={'resultSeconds': 6, 'errorSeconds': 10}, conversation={'followUpSeconds': 12, 'maxFollowUps': 2})
        return controller, agent

    async def test_result_stays_visible_for_configured_duration(self):
        controller, _ = self.controller()
        with patch('aurora_assistant.controller.asyncio.sleep', new_callable=AsyncMock) as sleep:
            await controller.handle('test')
        sleep.assert_awaited_with(6)
        controller.overlay.reset.assert_awaited_once()

    async def test_clarification_stays_open_and_carries_context(self):
        controller, agent = self.controller()
        agent.awaiting_reply = True
        agent.run.return_value = 'Which page?'
        await controller.handle('Open a page')
        self.assertTrue(controller.follow_up)
        controller.overlay.reset.assert_not_awaited()
        controller.overlay.state.assert_awaited_with('listening')
        agent.awaiting_reply = False
        agent.run.return_value = 'Opened.'
        with patch('aurora_assistant.controller.asyncio.sleep', new_callable=AsyncMock):
            await controller.handle('YouTube')
        request = agent.run.call_args.args[0]
        self.assertIn('Open a page', request)
        self.assertIn('Which page?', request)
        self.assertIn('YouTube', request)
        self.assertFalse(controller.follow_up)

    async def test_followup_silence_clears_context(self):
        controller, agent = self.controller()
        agent.awaiting_reply = True
        agent.run.return_value = 'Which device?'
        await controller.handle('mute')
        await controller.handle('')
        self.assertFalse(controller.follow_up)
        # Silence is not sent to a model or executed.
        agent.run.assert_awaited_once()
        controller.overlay.reset.assert_awaited_once()

    async def test_agent_timeout_keeps_error_visible(self):
        controller, agent = self.controller()
        controller.presentation['agentTimeoutSeconds'] = .01
        async def hang(_):
            await asyncio.Event().wait()
        agent.run.side_effect = hang
        with patch('aurora_assistant.controller.asyncio.sleep', new_callable=AsyncMock) as sleep:
            await controller.handle('test')
        sleep.assert_awaited_with(10)
        controller.overlay.state.assert_any_await('error')


class PortalTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, result):
        from dbus_next import Message, MessageType
        bus = Mock()
        bus.connect = AsyncMock(return_value=bus)
        handler = None
        def add(callback):
            nonlocal handler
            handler = callback
        bus.add_message_handler.side_effect = add
        async def call(message):
            if message.member == 'OpenURI':
                self.assertEqual(message.interface, 'org.freedesktop.portal.OpenURI')
                self.assertEqual(message.body[1], 'https://www.youtube.com/')
                handler(Message(message_type=MessageType.SIGNAL, sender=':1.2',
                    path='/org/freedesktop/portal/desktop/request/test', interface='org.freedesktop.portal.Request',
                    member='Response', signature='ua{sv}', body=[result, {}]))
                return Message(message_type=MessageType.METHOD_RETURN, reply_serial=1, sender=':1.2',
                    signature='o', body=['/org/freedesktop/portal/desktop/request/test'])
            return Message(message_type=MessageType.METHOD_RETURN, reply_serial=1)
        bus.call = AsyncMock(side_effect=call)
        with patch('dbus_next.aio.MessageBus', return_value=bus):
            try:
                return await open_url('https://www.youtube.com/')
            finally:
                bus.disconnect.assert_called_once()

    async def test_portal_success_and_early_signal(self):
        self.assertIn('accepted', await self.request(0))

    async def test_portal_denial_is_not_success(self):
        with self.assertRaises(RuntimeError):
            await self.request(1)


class DiagnosticTests(unittest.TestCase):
    def test_content_is_opt_in(self):
        with patch.object(telemetry.log, 'info') as log:
            telemetry.log_content = False
            telemetry.content('transcript.final', 'private words')
            self.assertNotIn('private words', log.call_args.args[0])
            telemetry.log_content = True
            telemetry.content('transcript.final', 'private words')
            self.assertIn('private words', log.call_args.args[0])
        telemetry.log_content = False

    def test_report_merges_user_and_system_time_order(self):
        from aurora_assistant.report import collect
        rows = [('', '', 0), (json.dumps({'__REALTIME_TIMESTAMP': '2000000', '_SYSTEMD_USER_UNIT': 'aurora-controller.service', 'MESSAGE': 'later'}), '', 0),
                (json.dumps({'__REALTIME_TIMESTAMP': '1000000', '_SYSTEMD_UNIT': 'aurora-models.service', 'MESSAGE': 'earlier'}), '', 0)]
        with patch('aurora_assistant.report.run', side_effect=rows):
            report = collect('30 minutes ago')
        self.assertLess(report.index('earlier'), report.index('later'))

    def test_since_argument_is_not_shell_code(self):
        from aurora_assistant.report import journal_command
        value = 'today; touch /tmp/should-not-exist'
        self.assertIn(value, journal_command(['aurora-controller.service'], value, True))
