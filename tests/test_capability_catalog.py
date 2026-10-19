import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from aurora_assistant.catalog import CapabilityCatalog
from aurora_assistant.kev import Kev
from aurora_assistant.main import show_service_failure


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = CapabilityCatalog()
        self.action = SimpleNamespace(name='dbus_inspect', argument={
            'bus': 'session', 'destination': 'org.mpris.MediaPlayer2.test', 'path': '/org/mpris/MediaPlayer2'})
        self.value = {'interfaces': [{'name': 'org.mpris.MediaPlayer2.Player',
            'methods': [{'name': 'Pause', 'input': '', 'output': ''},
                        {'name': 'Seek', 'input': 'x', 'output': ''}],
            'properties': [{'name': 'Volume', 'signature': 'd', 'access': 'readwrite'}]}]}

    def test_only_complete_candidates_and_search_order(self):
        self.catalog.observe(self.action, self.value)
        docs = self.catalog.search('volume')
        self.assertEqual(docs[0]['name'], 'Volume')
        seek = next(doc for doc in docs if doc['name'] == 'Seek')
        self.assertNotIn('candidate', seek)
        pause = next(doc for doc in docs if doc['name'] == 'Pause')
        self.assertEqual(pause['candidate']['argument']['argumentsJson'], '[]')
        self.assertIn('org.mpris.MediaPlayer2.Player', self.catalog.markdown())

    def test_snapshot_replacement_and_expiration(self):
        with patch('aurora_assistant.catalog.time.monotonic', return_value=1):
            self.catalog.observe(self.action, self.value)
            self.value['interfaces'].clear()
            self.assertEqual(len(self.catalog.documents()), 3)  # Owned snapshot.
        with patch('aurora_assistant.catalog.time.monotonic', return_value=302):
            self.assertEqual(self.catalog.documents(), [])
        self.catalog.observe(self.action, self.value)
        self.assertEqual(self.catalog.documents(), [])


class CatalogDecisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_capability_preserves_exact_action(self):
        action = {'name': 'dbus_call', 'argument': {'method': 'Pause', 'argumentsJson': '[]'}}
        kev = Kev({}, AsyncMock())
        kev.decide = AsyncMock(return_value={'capability': {'choice': '0', 'probabilities': {'0': .99, 'escalate': .01}}})
        result = await kev.discovered_plan('pause that player', [], [{'candidate': action}])
        self.assertEqual(result['actions'], [action])
        kev.decide.return_value['capability']['probabilities'] = {'0': .6, 'escalate': .4}
        self.assertIsNone(await kev.discovered_plan('pause that player', [], [{'candidate': action}]))

    async def test_unknown_option_never_selects_action(self):
        kev = Kev({}, AsyncMock())
        kev.decide = AsyncMock(return_value={'capability': {'choice': '99', 'probabilities': {'0': .99, 'escalate': .01}}})
        with self.assertRaises(ValueError):
            await kev.discovered_plan('do it', [], [{'candidate': {}}])

    async def test_service_error_is_visible_and_cancellation_is_quiet(self):
        overlay = AsyncMock()
        with patch('aurora_assistant.main.asyncio.sleep', new_callable=AsyncMock) as sleep:
            self.assertFalse(await show_service_failure(overlay, 10, RuntimeError, RuntimeError(), None))
            sleep.assert_awaited_once_with(10)
        overlay.state.assert_awaited_with('error')
        overlay.reset_mock()
        await show_service_failure(overlay, 10, asyncio.CancelledError, asyncio.CancelledError(), None)
        overlay.state.assert_not_awaited()
