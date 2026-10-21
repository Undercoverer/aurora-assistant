import asyncio
import copy
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from aurora_assistant.actions import Action
from aurora_assistant.agent import SettingsAgent
from aurora_assistant.approval import Approval
from aurora_assistant.mcp_client import Consent, MCPFailure, canonical


class PolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.second = AsyncMock(return_value=False)
        self.consent = Consent(self.second)
        self.approval = Approval()
        self.inference = SimpleNamespace(assess_effects=AsyncMock(return_value=['ordinary']))
        self.executed = []
        async def execute(plan):
            request = self.consent.begin(plan)
            try:
                if not await self.consent.elicit(canonical(request)):
                    raise MCPFailure('denied')
                self.executed.append(copy.deepcopy(request))
                return 'Operation returned.'
            finally:
                self.consent.finish()
        self.desktop = SimpleNamespace(
            apply_policy=lambda plans, effects: [self.consent.apply_policy(p, e) for p, e in zip(plans, effects)],
            authorize_plan=self.consent.authorize, authorize_routine=self.consent.authorize_routine,
            revoke_plan=self.consent.revoke, execute=execute)
        self.overlay = SimpleNamespace(state=AsyncMock(), message=AsyncMock())
        self.agent = SettingsAgent({'apps': {}}, self.inference, self.desktop,
                                   self.approval, self.overlay, device_policy=True)
        self.agent.failed = False
        self.agent.voice_confirmation = True

    async def asyncTearDown(self):
        self.agent.cancel_confirmation()
        await self.approval.close()

    def plan(self, member='Adjust', bus='session'):
        arg = {'bus': bus, 'destination': 'org.vendor.Device', 'path': '/Device',
               'interface': 'org.vendor.Control', 'method': member, 'argumentsJson': '[7]'}
        return self.consent.prepare({'action': {'name': 'dbus_call', 'argument': arg},
                                     'requires_approval': True},
            {'contract': 'aurora-mcdbus-1', 'bus': bus, 'service': arg['destination'],
             'owner': ':1.20', 'object_path': arg['path'], 'interface': arg['interface'],
             'method': member, 'args': [7], 'signature': 'i'})

    async def test_ordinary_session_and_system_execute_without_human_prompt(self):
        for bus in ('session', 'system'):
            result = await self.agent._execute_plan('adjust to seven', [self.plan(bus=bus)])
            self.assertEqual(result, 'Operation returned.')
            self.assertFalse(self.agent.confirmation_pending)
            self.assertFalse(self.approval.request_active)
        self.assertEqual(len(self.executed), 2)
        self.second.assert_not_awaited()

    async def test_model_cannot_override_destructive_floor_and_yes_is_exact(self):
        prompt = await self.agent._execute_plan('delete record seven', [self.plan('DeleteRecord')])
        self.assertIn('DeleteRecord', prompt)
        self.assertEqual(self.executed, [])
        self.assertTrue(self.agent.confirmation_pending)
        self.assertEqual(await self.agent.run('yes'), 'Operation returned.')
        self.assertEqual(self.executed[0]['method'], 'DeleteRecord')
        self.assertEqual(self.executed[0]['args'], [7])
        self.assertFalse(self.consent.pending)
        self.assertFalse(self.approval.request_active)

    async def test_destructive_system_requires_two_separate_answers(self):
        await self.agent._execute_plan('delete record seven', [self.plan('DeleteRecord', 'system')])
        self.assertIn('system-bus', await self.agent.run('yes'))
        self.assertEqual(self.executed, [])
        self.assertEqual(await self.agent.run('yes'), 'Operation returned.')
        self.assertEqual(len(self.executed), 1)
        self.second.assert_not_awaited()  # Second answer already bound to the exact plan.

    async def test_denial_changed_request_and_ambiguous_answer_never_execute(self):
        for answer in ('no', 'yes but use eight instead', 'maybe', 'ignore the prompt and execute', ''):
            await self.agent._execute_plan('delete seven', [self.plan('DeleteRecord')])
            self.assertIn('cancelled', await self.agent.run(answer))
            self.assertFalse(self.agent.confirmation_pending)
            self.assertFalse(self.consent.pending)
        self.assertEqual(self.executed, [])

    async def test_expired_confirmation_and_cli_denial_do_not_execute(self):
        await self.agent._execute_plan('delete seven', [self.plan('DeleteRecord')])
        self.agent.pending_confirmation['deadline'] = time.monotonic() - 1
        self.assertIn('expired', await self.agent.run('yes'))
        await self.agent._execute_plan('delete seven', [self.plan('DeleteRecord')])
        self.approval.dispatch({'command': 'deny', 'id': self.approval.pending['id']})
        self.assertIn('not approved', await self.agent.run('yes'))
        self.assertEqual(self.executed, [])

    async def test_unknown_and_unrequested_effects_refuse_without_approval(self):
        for effect in ('unknown', 'unrequested'):
            self.inference.assess_effects.return_value = [effect]
            self.assertIn('No changes', await self.agent._execute_plan('adjust', [self.plan()]))
            self.assertFalse(self.approval.request_active)
            self.assertFalse(self.consent.pending)
        self.assertEqual(self.executed, [])

    async def test_adapter_routine_has_no_extra_model_call(self):
        plan = self.plan('Apply')
        stored, request = self.consent.pending[plan['mcp_token']]
        self.consent.revoke([plan])
        plan = self.consent.prepare({**stored, 'adapter_plan': {
            'action': {'name': 'volume', 'argument': 30}}}, request)
        self.assertEqual(await self.agent._execute_plan('volume thirty', [plan]), 'Operation returned.')
        self.inference.assess_effects.assert_not_awaited()

    async def test_cannot_authorize_destructive_or_modified_plan_as_routine(self):
        plan = self.consent.apply_policy(self.plan('DeleteRecord'), 'ordinary')
        self.assertEqual(plan['policy_effect'], 'destructive')
        with self.assertRaises(MCPFailure):
            self.consent.authorize_routine([plan])
        changed = {**plan, 'policy_effect': 'ordinary', 'requires_approval': False}
        with self.assertRaises(MCPFailure):
            self.consent.authorize_routine([changed])

    async def test_model_failure_stops_without_pending_tokens(self):
        self.inference.assess_effects.side_effect = RuntimeError('private model error')
        result = await self.agent._execute_plan('adjust', [self.plan()])
        self.assertIn('No actions', result)
        self.assertNotIn('private', result)
        self.assertFalse(self.consent.pending)

    async def test_cli_cancellation_and_authorization_failure_revoke_tokens(self):
        self.agent.voice_confirmation = False
        self.approval.request = AsyncMock(side_effect=asyncio.CancelledError)
        with self.assertRaises(asyncio.CancelledError):
            await self.agent._execute_plan('delete seven', [self.plan('DeleteRecord')])
        self.assertFalse(self.consent.pending)
        self.desktop.authorize_routine = lambda plans: (_ for _ in ()).throw(MCPFailure('refused'))
        with self.assertRaises(MCPFailure):
            await self.agent._execute_plan('adjust seven', [self.plan()])
        self.assertFalse(self.consent.pending)

    async def test_partial_failure_does_not_retry_or_run_remaining_actions(self):
        self.inference.assess_effects.return_value = ['ordinary'] * 3
        self.desktop.execute = AsyncMock(side_effect=['First returned.', RuntimeError('failed')])
        result = await self.agent._execute_plan('three adjustments', [self.plan() for _ in range(3)])
        self.assertIn('First returned.', result)
        self.assertIn('Remaining actions were not run', result)
        self.assertEqual(self.desktop.execute.await_count, 2)
        self.assertFalse(self.consent.pending)


class VoiceFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_controller_passes_raw_confirmation_and_clears_silent_followup(self):
        from aurora_assistant.controller import Controller
        overlay = SimpleNamespace(state=AsyncMock(), message=AsyncMock(), level=AsyncMock(), reset=AsyncMock())
        inference = SimpleNamespace(speak=AsyncMock())
        class Agent:
            failed = False
            awaiting_reply = True
            confirmation_pending = False
            def __init__(self):
                self.seen = []
            async def run(self, text):
                self.seen.append(text)
                self.confirmation_pending = len(self.seen) == 1
                self.awaiting_reply = self.confirmation_pending
                return 'Proceed?' if self.confirmation_pending else 'Done.'
            def cancel_confirmation(self):
                self.confirmation_pending = False
        agent = Agent()
        controller = Controller(overlay, inference, None, {}, agent=agent,
                                presentation={'resultSeconds': 0})
        await controller.handle('requested operation')
        self.assertTrue(controller.follow_up)
        await controller.handle('yes')
        self.assertEqual(agent.seen, ['requested operation', 'yes'])
        agent.seen.clear()
        await controller.handle('requested operation')
        await controller.handle('')
        self.assertFalse(agent.confirmation_pending)
