import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aurora_assistant.actions import Action, validate, PlanValidationError
from aurora_assistant.agent import SettingsAgent
from aurora_assistant.catalog import CapabilityCatalog
from aurora_assistant.candidates import desktop_candidates
from aurora_assistant.desktop_bus import DesktopService
from aurora_assistant.kev import Kev, common_plan
from test_desktop_bus import invoke


def plan(name, argument):
    return {'actions': [{'name': name, 'argument': argument}], 'reply': ''}


class DecisionWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def agent(self):
        inference, desktop, approval, overlay = [AsyncMock() for _ in range(4)]
        inference.catalog = CapabilityCatalog()
        return SettingsAgent({'apps': {}, 'settings': {'enable': True, 'maxRounds': 4},
                              'kev': {'enable': True, 'announceEscalation': False}},
                             inference, desktop, approval, overlay)

    async def test_clock_answer_comes_from_dbus_without_chat_generation(self):
        service = DesktopService({'apps': {}, 'commands': {}})
        fixed = datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc)
        with patch('datetime.datetime') as clock:
            clock.now.return_value.astimezone.return_value = fixed
            clock_data = json.loads(await invoke(service, 'Read', 'clock'))
        agent = self.agent()
        agent.inference.quick_plan.return_value = common_plan('What time is it?')
        agent.desktop.read.return_value = clock_data
        self.assertEqual(await agent.run('What time is it?'), clock_data['reply'])
        self.assertIn('09:30', clock_data['reply'])
        agent.inference.plan.assert_not_awaited()
        agent.inference.review.assert_not_awaited()
        agent.desktop.prepare.assert_not_awaited()
        agent.approval.request.assert_not_awaited()

    async def test_exact_mute_volume_youtube_skip_redundant_model_review(self):
        for request in ('Mute the computer', 'set volume to 12', 'open youtube'):
            with self.subTest(request=request):
                agent = self.agent()
                selected = common_plan(request)
                agent.inference.quick_plan.return_value = selected
                agent.desktop.prepare.return_value = {
                    'action': selected['actions'][0], 'requires_approval': False}
                agent.desktop.execute.return_value = 'Verified.'
                self.assertEqual(await agent.run(request), 'Verified.')
                agent.inference.review.assert_not_awaited()
                agent.approval.request.assert_not_awaited()
                agent.desktop.execute.assert_awaited_once()

    async def test_local_policy_never_overrides_adapter_approval(self):
        agent = self.agent()
        agent.inference.quick_plan.return_value = plan('mute', True)
        agent.desktop.prepare.return_value = {'action': {'name': 'mute', 'argument': True}, 'requires_approval': True}
        agent.inference.review.return_value = {'decision': 'allow', 'reason': 'Requested'}
        agent.approval.request.return_value = False
        await agent.run('mute the computer')
        agent.approval.request.assert_awaited_once()
        agent.desktop.execute.assert_not_awaited()

    async def test_invalid_arguments_are_replanned_without_execution(self):
        agent = self.agent()
        agent.inference.quick_plan.return_value = plan('volume', '12')
        agent.inference.plan.return_value = plan('volume', 12)
        agent.desktop.prepare.return_value = {'action': {'name': 'volume', 'argument': 12}, 'requires_approval': False}
        agent.desktop.execute.return_value = 'Volume set to 12 percent.'
        self.assertIn('12 percent', await agent.run('set volume to 12'))
        self.assertEqual(agent.desktop.prepare.await_args.args[0], Action('volume', 12))
        agent.desktop.prepare.assert_awaited_once()
        self.assertIn('validation_error', agent.inference.plan.call_args.kwargs['evidence'][0])

    async def test_repeated_invalid_json_stops_without_desktop_calls(self):
        agent = self.agent()
        agent.inference.quick_plan.return_value = None
        agent.inference.plan.side_effect = PlanValidationError('Model response is not valid JSON')
        self.assertIn('twice', await agent.run('something unusual'))
        self.assertEqual(agent.inference.plan.await_count, 2)
        agent.desktop.prepare.assert_not_awaited()
        agent.desktop.execute.assert_not_awaited()

    async def test_semantic_selection_uses_supplied_candidate_not_generated_arguments(self):
        kev = Kev({}, AsyncMock())
        async def choose(state, questions):
            criteria = questions['capability']['criteria']
            selected = next(k for k, v in criteria.items() if 'exactly 12 percent' in v)
            return {'capability': {'choice': selected, 'probabilities': {
                k: .99 if k == selected else .01 if k == 'escalate' else 0 for k in criteria}}}
        kev.decide = AsyncMock(side_effect=choose)
        self.assertEqual(await kev.route('Make the speakers 12 percent loud'), plan('volume', 12))
        self.assertEqual(kev.decide.await_count, 1)

    async def test_uncertain_multi_action_selection_escalates_without_partial_plan(self):
        kev = Kev({}, AsyncMock())
        async def choose(state, questions):
            return {'capability': {'choice': 'escalate', 'probabilities': {
                k: float(k == 'escalate') for k in questions['capability']['criteria']}}}
        kev.decide = AsyncMock(side_effect=choose)
        self.assertIsNone(await kev.route('open youtube and delete my documents'))

    def test_candidate_values_are_bounded_and_typed(self):
        for request in ('volume 200', 'volume -12', 'volume 12.5', 'volume 12'):
            docs = desktop_candidates(request)
            for doc in docs:
                validate({'actions': [doc['candidate']], 'reply': ''}, {}, settings=True)
            values = [d['candidate']['argument'] for d in docs if d['candidate']['name'] == 'volume']
            self.assertEqual(values, [12] if request == 'volume 12' else [])

    def test_observed_apps_and_boolean_properties_become_choices(self):
        catalog = CapabilityCatalog()
        catalog.observe(Action('desktop_read', 'applications'), {'org.kde.dolphin.desktop': 'Dolphin'})
        docs = catalog.search('Dolphin')
        self.assertEqual(docs[0]['candidate'], {'name': 'launch_app', 'argument': 'org.kde.dolphin.desktop'})
        catalog.observe(SimpleNamespace(name='dbus_inspect', argument={
            'bus': 'session', 'destination': 'org.kde.example', 'path': '/Settings'}), {
            'interfaces': [{'name': 'org.kde.example.Settings', 'properties': [
                {'name': 'Enabled', 'signature': 'b', 'access': 'readwrite'}]}]})
        writes = [d['candidate'] for d in catalog.documents() if d.get('candidate', {}).get('name') == 'dbus_set']
        self.assertEqual({w['argument']['valueJson'] for w in writes}, {'true', 'false'})
