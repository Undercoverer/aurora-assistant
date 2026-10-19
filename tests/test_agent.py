import asyncio
import unittest
from unittest.mock import AsyncMock, Mock
from aurora_assistant.agent import SettingsAgent
from aurora_assistant.approval import Approval


def plan(name, arg):
    return {'actions': [{'name': name, 'argument': arg}], 'reply': ''}


class AgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.inference, self.desktop, self.approval, self.overlay = [AsyncMock() for _ in range(4)]
        self.inference.review.return_value = {'decision': 'allow', 'reason': 'Requested change'}
        self.desktop.prepare.return_value = {'action': {'name': 'theme', 'argument': 'x'}, 'requires_approval': False}
        self.desktop.execute.return_value = 'Completed.'
        self.agent = SettingsAgent({'apps': {}, 'settings': {'maxRounds': 3}}, self.inference,
                                   self.desktop, self.approval, self.overlay)

    async def test_discovery_then_execution(self):
        self.inference.plan.side_effect = [plan('desktop_read', 'themes'), plan('theme', 'BreezeDark')]
        self.desktop.read.return_value = ['BreezeDark']
        self.assertEqual(await self.agent.run('Use Breeze Dark'), 'Completed.')
        self.desktop.read.assert_awaited_once()
        self.desktop.execute.assert_awaited_once()
        self.approval.request.assert_not_awaited()

    async def test_unknown_write_needs_human_even_when_reviewer_allows(self):
        self.inference.plan.return_value = plan('theme', 'BreezeDark')
        self.desktop.prepare.return_value['requires_approval'] = True
        self.approval.request.return_value = False
        await self.agent.run('Change a setting')
        self.approval.request.assert_awaited_once()
        self.desktop.execute.assert_not_awaited()

    async def test_reviewer_failure_requires_approval(self):
        self.inference.plan.return_value = plan('theme', 'BreezeDark')
        self.inference.review.side_effect = RuntimeError()
        self.approval.request.return_value = False
        await self.agent.run('Change theme')
        self.approval.request.assert_awaited_once()
        self.desktop.execute.assert_not_awaited()

    async def test_blocked_plan_does_not_execute(self):
        self.inference.plan.return_value = plan('theme', 'BreezeDark')
        self.inference.review.return_value = {'decision': 'block', 'reason': 'Not requested'}
        await self.agent.run('Read theme')
        self.desktop.execute.assert_not_awaited()

    async def test_microphone_is_last_and_partial_failure_stops(self):
        self.inference.plan.return_value = {'actions': [
            {'name': 'microphone_mute', 'argument': True}, {'name': 'media', 'argument': 'pause'}], 'reply': ''}
        self.desktop.execute.side_effect = RuntimeError()
        await self.agent.run('Mute microphone and pause playback')
        order = [c.args[0].name for c in self.desktop.prepare.call_args_list]
        self.assertEqual(order, ['media', 'microphone_mute'])
        self.assertTrue(self.agent.failed)
        self.desktop.execute.assert_awaited_once()


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_id_single_use(self):
        approval = Approval()
        task = asyncio.create_task(approval.request({'plan': ['test']}, AsyncMock()))
        await asyncio.sleep(0)
        with self.assertRaises(ValueError):
            approval.dispatch({'command': 'approve', 'id': 'wrong'})
        identity = approval.dispatch({'command': 'pending'})['pending']['id']
        self.assertTrue(approval.dispatch({'command': 'approve', 'id': identity})['accepted'])
        self.assertTrue(await task)
        with self.assertRaises(ValueError):
            approval.dispatch({'command': 'approve', 'id': identity})

    async def test_timeout_does_not_approve(self):
        approval = Approval()
        self.assertFalse(await approval.request({'plan': []}, AsyncMock(), timeout=0.001))
        self.assertIsNone(approval.pending)
