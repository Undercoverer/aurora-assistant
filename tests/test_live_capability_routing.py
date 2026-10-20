"""Live transport and fault-injection tests; model judgments remain mocked."""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch
from dbus_next.service import ServiceInterface

from aurora_assistant.actions import Action
from aurora_assistant.catalog import CapabilityCatalog
from aurora_assistant.candidates import finite_values
from aurora_assistant.desktop_bus import DesktopService, RemoteDesktop, NAME, PATH
from aurora_assistant.discovery import scan
from aurora_assistant.inference import Inference
from aurora_assistant.kev import Kev
from aurora_assistant.settings import BusAccess


def metadata():
    service = DesktopService({'apps': {}, 'commands': {}})
    method = next(m for m in ServiceInterface._get_methods(service) if m.name == 'Describe')
    return {'source': {'bus': 'session', 'destination': NAME, 'path': PATH,
                       'interface': service.name, 'owner': ':1.42'},
            'description': json.loads(method.fn(service))}


def answer(question, selected, probability=1.):
    criteria = question['criteria']
    other = (1 - probability) / (len(criteria) - 1)
    return {'choice': selected, 'probabilities': {key: probability if key == selected else other for key in criteria}}


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    def docs(self):
        catalog = CapabilityCatalog()
        catalog.advertise(metadata())
        return catalog.routing_documents('irrelevant wording')

    async def test_empty_discovery_cannot_invent_a_tool(self):
        kev = Kev({}, AsyncMock())
        kev.decide = AsyncMock()
        self.assertIsNone(await kev.route('mute the speakers'))
        kev.decide.assert_not_awaited()

    async def test_semantic_operation_and_number_word_use_advertised_domain(self):
        docs = self.docs()
        index = next(str(i) for i, doc in enumerate(docs) if doc['name'] == 'volume')
        kev = Kev({}, AsyncMock())
        states = []
        async def decide(state, questions):
            states.append(state)
            name, question = next(iter(questions.items()))
            choice = index if name == 'capability' else next(k for k, v in question['criteria'].items() if v == '12')
            return {name: answer(question, choice)}
        kev.decide = AsyncMock(side_effect=decide)
        result = await kev.route('Make the loudness twelve percent, please.', documents=docs)
        self.assertEqual(result['actions'], [{'name': 'volume', 'argument': 12}])
        self.assertEqual(states[0], states[1])  # Both stages share an identical state prefix.
        self.assertIn('twelve percent', states[0])

    async def test_free_text_url_hands_off_instead_of_using_a_predefined_site(self):
        docs = self.docs()
        index = next(str(i) for i, doc in enumerate(docs) if doc['name'] == 'open_url')
        kev = Kev({}, AsyncMock())
        async def decide(state, questions):
            return {'capability': answer(questions['capability'], index)}
        kev.decide = AsyncMock(side_effect=decide)
        self.assertIsNone(await kev.route('Open an arbitrary website', documents=docs))
        self.assertEqual(kev.decide.await_count, 1)
        self.assertNotIn('youtube', json.dumps(docs).lower())

    async def test_nested_group_selection_preserves_global_capability_indices(self):
        docs = [{'target': {'bus': 'session', 'destination': f'org.example.Service{i // 20}'},
                 'name': f'Operation{i}', 'description': f'Observed operation {i}',
                 'candidate': {'name': 'dbus_call', 'argument': {'method': f'Operation{i}'}}}
                for i in range(40)]
        kev = Kev({}, AsyncMock())
        calls = []
        async def decide(state, questions):
            name, question = next(iter(questions.items()))
            calls.append(name)
            if name == 'group':
                selected = next(k for k, v in question['criteria'].items() if 'Service1' in v)
            else:
                self.assertNotIn('0', question['criteria'])
                selected = '31'
            return {name: answer(question, selected)}
        kev.decide = AsyncMock(side_effect=decide)
        result = await kev.route('Use the observed function', documents=docs)
        self.assertEqual(calls, ['group', 'capability'])
        self.assertEqual(result['actions'][0]['argument']['method'], 'Operation31')

    async def test_uncertain_or_invalid_arguments_produce_no_plan(self):
        docs = self.docs()
        index = next(str(i) for i, doc in enumerate(docs) if doc['name'] == 'mute')
        kev = Kev({}, AsyncMock())
        async def decide(state, questions):
            name, question = next(iter(questions.items()))
            return {name: answer(question, index if name == 'capability' else 'escalate')}
        kev.decide = AsyncMock(side_effect=decide)
        self.assertIsNone(await kev.route('Maybe silence it later', documents=docs))
        with self.assertRaises(ValueError):
            kev.selection({'choice': 'invented', 'probabilities': {'invented': 1}}, {'0': 'known', 'escalate': 'other'})
        self.assertIsNone(kev.selection({'choice': '0', 'probabilities': {'0': .5, 'escalate': .5}}, {'0': 'known', 'escalate': 'other'}))

    async def test_oversize_request_uses_tokenizer_and_never_truncates(self):
        import httpx
        request = AsyncMock(return_value=httpx.Response(200, json={'tokens': list(range(4096))},
                                                       request=httpx.Request('POST', 'http://localhost/tokenize')))
        kev = Kev({'contextSize': 4096}, request)
        with self.assertRaisesRegex(ValueError, 'not truncated'):
            await kev.decide('x' * 9000, {'x': {'type': 'noul', 'instructions': 'test'}})
        self.assertEqual(request.await_args.args[1], 'http://127.0.0.1:8008/tokenize')
        self.assertIn('x' * 9000, request.await_args.kwargs['json']['content'])
        request.assert_awaited_once()

    def test_domains_do_not_depend_on_user_words(self):
        self.assertEqual(finite_values({'type': 'integer', 'minimum': 0, 'maximum': 100}), list(range(101)))
        for schema in ({'type': 'integer'}, {'type': 'integer', 'minimum': 0, 'maximum': 1000000},
                       {'type': 'integer', 'minimum': False, 'maximum': 2}, {'enum': []}, {'enum': ['x', 'x']}):
            self.assertIsNone(finite_values(schema))

    def test_stable_prefix_and_snapshot_replacement(self):
        catalog = CapabilityCatalog()
        data = metadata()
        catalog.advertise(data)
        self.assertEqual(catalog.routing_documents('mute'), catalog.routing_documents('silence'))
        data['description']['actions'].clear()
        self.assertTrue(catalog.advertised())
        catalog.advertise(data)
        self.assertEqual(catalog.advertised(), [])
        with self.assertRaises(ValueError):
            catalog.advertise({'description': 'invalid'})
        self.assertEqual(catalog.advertised(), [])

    async def test_failed_refresh_removes_stale_adapter_tools(self):
        client = Inference({'apps': {}})
        client.catalog.advertise(metadata())
        client.capability_source = AsyncMock(side_effect=RuntimeError('offline'))
        try:
            await client.refresh_capabilities()
            self.assertEqual(client.catalog.advertised(), [])
        finally:
            await client.close()

    async def test_discovery_follows_only_observed_child_paths_and_is_bounded(self):
        bus = AsyncMock()
        async def read(action):
            if action.name == 'dbus_list':
                return ['org.example.Live'] if action.argument == 'session' else []
            path = action.argument['path']
            return {'interfaces': [], 'children': ['Device', '../bad'] if path == '/' else []}
        bus.read.side_effect = read
        catalog = CapabilityCatalog()
        await scan(catalog, bus, max_objects=2)
        paths = [call.args[0].argument['path'] for call in bus.read.call_args_list if call.args[0].name == 'dbus_inspect']
        self.assertEqual(paths, ['/', '/Device'])

    async def test_changed_owner_requires_new_discovery_before_prepare(self):
        remote = RemoteDesktop(AsyncMock(), Mock())
        remote.observed_owner = ':1.1'
        remote.owner = AsyncMock(return_value=':1.2')
        with self.assertRaisesRegex(RuntimeError, 'refresh discovery'):
            await remote.prepare(Action('mute', True))
        remote.bus.call.assert_not_awaited()


@unittest.skipUnless(os.environ.get('DBUS_SESSION_BUS_ADDRESS'), 'Needs isolated session bus')
class LiveDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_bus_advertisement_routing_prepare_and_apply(self):
        from dbus_next.aio import MessageBus
        server = await MessageBus().connect()
        service = DesktopService({'apps': {}, 'commands': {}})
        service.desktop.prepare = AsyncMock(side_effect=lambda action: {
            'action': {'name': action.name, 'argument': action.argument}, 'requires_approval': False})
        service.desktop.execute = AsyncMock(return_value='Verified mute state.')
        server.export(PATH, service)
        await server.request_name(NAME)
        remote = RemoteDesktop(BusAccess({}), Mock())
        try:
            catalog = CapabilityCatalog()
            catalog.advertise(await remote.describe())
            docs = catalog.routing_documents('Silence this computer')
            index = next(str(i) for i, doc in enumerate(docs) if doc['name'] == 'mute')
            kev = Kev({}, AsyncMock())
            async def decide(state, questions):
                name, question = next(iter(questions.items()))
                choice = index if name == 'capability' else next(k for k, v in question['criteria'].items() if v == 'true')
                return {name: answer(question, choice)}
            kev.decide = AsyncMock(side_effect=decide)
            plan = await kev.route('Silence this computer', documents=docs)
            prepared = await remote.prepare(Action(**plan['actions'][0]))
            self.assertEqual(await remote.execute(prepared), 'Verified mute state.')
            with self.assertRaises(RuntimeError):
                await remote.execute(prepared)
            service.desktop.execute.assert_awaited_once()
        finally:
            server.disconnect()
            await server.wait_for_disconnect()

