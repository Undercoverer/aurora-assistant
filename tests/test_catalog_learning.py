import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aurora_assistant.actions import Action
from aurora_assistant.catalog import CapabilityCatalog
from aurora_assistant.catalog_notes import CatalogNotes, fingerprint
from aurora_assistant.catalog_learning import CatalogLearner
from aurora_assistant.discovery import scan, DiscoveryCursor


def observed(catalog, signature=''):
    catalog.observe(Action('dbus_inspect', {'bus': 'session', 'destination': 'org.example.Player', 'path': '/Player'}),
                    {'interfaces': [{'name': 'org.example.Player', 'methods': [
                        {'name': 'Pause', 'input': signature, 'output': ''}]}]})


NOTE = {'summary': 'Likely pauses playback.', 'unknowns': 'Exact player behavior needs documentation.'}


class NotesTests(unittest.TestCase):
    def test_restart_reuses_notes_only_after_live_rediscovery(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'cache' / 'notes.json'
            notes = CatalogNotes('planner', path)
            catalog = CapabilityCatalog(notes)
            observed(catalog)
            document = catalog.documents()[0]
            notes.put(document, NOTE)
            restarted = CapabilityCatalog(CatalogNotes('planner', path))
            self.assertEqual(restarted.documents(), [])
            observed(restarted)
            self.assertEqual(restarted.documents()[0]['semantic_note']['summary'], NOTE['summary'])
            self.assertEqual(restarted.documents()[0]['candidate'], document['candidate'])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            observed(restarted, 'i')
            self.assertNotIn('semantic_note', restarted.documents()[0])
            self.assertNotIn('candidate', restarted.documents()[0])

    def test_age_model_and_schema_changes_invalidate_explanation(self):
        notes = CatalogNotes('first')
        catalog = CapabilityCatalog(notes)
        observed(catalog)
        document = catalog.documents()[0]
        notes.put(document, NOTE)
        notes.model = 'second'
        self.assertIsNone(notes.get(document))
        notes.model = 'first'
        notes.entries[fingerprint(document)]['created'] = 0
        self.assertIsNone(notes.get(document))

    def test_explanation_cannot_add_executable_fields(self):
        notes = CatalogNotes('planner')
        catalog = CapabilityCatalog(notes)
        observed(catalog)
        with self.assertRaises(ValueError):
            notes.put(catalog.documents()[0], {**NOTE, 'candidate': {'name': 'shell'}})
        self.assertEqual(notes.entries, {})

    def test_corrupt_cache_and_symlink_are_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'notes.json'
            path.write_text('{broken')
            self.assertEqual(CatalogNotes('planner', path).entries, {})
            path.unlink()
            target = Path(root) / 'other.json'
            target.write_text(json.dumps({'version': 1, 'entries': {}}))
            path.symlink_to(target)
            self.assertEqual(CatalogNotes('planner', path).entries, {})

    def test_empty_roots_do_not_evict_live_capabilities(self):
        catalog = CapabilityCatalog()
        observed(catalog)
        for i in range(40):
            catalog.observe(Action('dbus_inspect', {'bus': 'session',
                'destination': f'org.example.Root{i}', 'path': '/'}),
                {'interfaces': [], 'children': ['Device']})
        self.assertEqual(catalog.status()['live_documents'], 1)
        self.assertEqual(catalog.documents()[0]['name'], 'Pause')

    def test_status_has_counts_without_note_content(self):
        from aurora_assistant.approval import Approval
        catalog = CapabilityCatalog(CatalogNotes('planner'))
        observed(catalog)
        catalog.notes.put(catalog.documents()[0], NOTE)
        control = Approval()
        control.catalog = catalog
        status = control.dispatch({'command': 'catalog-status'})
        self.assertEqual(status['explained_live_documents'], 1)
        self.assertNotIn(NOTE['summary'], json.dumps(status))


class LearningTests(unittest.IsolatedAsyncioTestCase):
    def setup_learner(self):
        catalog = CapabilityCatalog(CatalogNotes('planner'))
        observed(catalog)
        inference = SimpleNamespace(catalog=catalog, config={'llm': {'model': 'planner'}},
                                    _structured_response=AsyncMock(return_value=NOTE))
        return CatalogLearner(inference, {}), inference

    async def test_enrichment_has_no_action_tools_and_is_cached(self):
        learner, inference = self.setup_learner()
        await learner.explain_one()
        request = inference._structured_response.call_args.kwargs
        self.assertEqual(request['response_name'], 'capability_explanation')
        self.assertNotIn('actions', request['response_schema']['properties'])
        self.assertEqual(inference.catalog.documents()[0]['semantic_note']['provenance'], 'model_inferred_unverified')
        await learner.explain_one()
        self.assertEqual(inference._structured_response.await_count, 1)
        self.assertIn('Unverified model explanation', inference.catalog.markdown())

    async def test_changed_observation_during_inference_discards_answer(self):
        learner, inference = self.setup_learner()
        async def changed(**kwargs):
            observed(inference.catalog, 's')
            return NOTE
        inference._structured_response.side_effect = changed
        await learner.explain_one()
        self.assertEqual(inference.catalog.notes.entries, {})

    async def test_activity_cancels_in_flight_request(self):
        learner, inference = self.setup_learner()
        entered = asyncio.Event()
        async def waiting(**kwargs):
            entered.set()
            await asyncio.Event().wait()
        inference._structured_response.side_effect = waiting
        learner.request_task = asyncio.create_task(learner.explain_one())
        await entered.wait()
        learner.activity()
        with self.assertRaises(asyncio.CancelledError):
            await learner.request_task
        self.assertEqual(inference.catalog.notes.entries, {})
        self.assertTrue(learner.busy)
        learner.activity(False)
        self.assertFalse(learner.busy)

    async def test_failed_member_does_not_block_later_members(self):
        learner, inference = self.setup_learner()
        inference._structured_response.side_effect = ValueError('bad response')
        with self.assertRaises(ValueError):
            await learner.explain_one()
        await learner.explain_one()
        self.assertEqual(inference._structured_response.await_count, 1)

    async def test_discovery_continues_queue_across_small_sweeps(self):
        catalog = CapabilityCatalog()
        cursor = DiscoveryCursor()
        bus = SimpleNamespace(read=AsyncMock())
        async def read(action):
            if action.name == 'dbus_list':
                return ['org.example.A', 'org.example.B'] if action.argument == 'session' else []
            return {'interfaces': [], 'children': ['Device'] if action.argument['path'] == '/' else []}
        bus.read.side_effect = read
        for _ in range(4):
            await scan(catalog, bus, max_objects=1, cursor=cursor)
        inspected = [c.args[0].argument for c in bus.read.call_args_list if c.args[0].name == 'dbus_inspect']
        self.assertEqual([(a['destination'], a['path']) for a in inspected],
                         [('org.example.A', '/'), ('org.example.A', '/Device'),
                          ('org.example.B', '/'), ('org.example.B', '/Device')])
        self.assertFalse(cursor.queue)
