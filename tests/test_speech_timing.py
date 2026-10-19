import asyncio
import unittest
from unittest.mock import AsyncMock
from aurora_assistant.speech_timing import PlaybackClock, text_chunks, validate_marks
from aurora_assistant.agent import SettingsAgent


class TimingTests(unittest.TestCase):
    def test_clock_waits_for_dac_not_buffer_submission(self):
        clock = PlaybackClock()
        clock.record(0, 10., 100)
        clock.record(100, 11., 100)
        self.assertIsNone(clock.position(9.5, 100))
        self.assertAlmostEqual(clock.position(10.5, 100), .5)
        self.assertAlmostEqual(clock.position(11.5, 100), 1.5)
        self.assertEqual(clock.position(20., 100), 2.)

    def test_chunks_preserve_original_text_and_offsets(self):
        text = 'First words. Then a longer sentence, with punctuation! ' * 9
        chunks = list(text_chunks(text))
        self.assertEqual(''.join(t for _, t in chunks), text)
        for offset, chunk in chunks:
            self.assertEqual(text[offset:offset + len(chunk)], chunk)
            self.assertLessEqual(len(chunk), 180)

    def test_invalid_timestamps_are_rejected(self):
        valid = [{'start': .2, 'end': .5, 'charEnd': 3}, {'start': .6, 'end': 1., 'charEnd': 7}]
        validate_marks(valid, 'one two', 1.)
        for marks in [[], [{'start': float('nan'), 'end': 1., 'charEnd': 7}],
                      [{'start': 0., 'end': 2., 'charEnd': 7}],
                      [{'start': 0., 'end': 1., 'charEnd': 3}],
                      [{'start': .8, 'end': 1., 'charEnd': 3}, {'start': .4, 'end': .7, 'charEnd': 7}]]:
            with self.assertRaises(ValueError):
                validate_marks(marks, 'one two', 1.)


class FeedbackTests(unittest.IsolatedAsyncioTestCase):
    def agent(self):
        inference, desktop, approval, overlay = [AsyncMock() for _ in range(4)]
        return SettingsAgent({'apps': {}, 'kev': {'enable': True}}, inference, desktop, approval, overlay)

    async def test_notice_and_planner_overlap(self):
        agent = self.agent()
        planning_started = asyncio.Event()
        speech_started = asyncio.Event()
        async def work():
            planning_started.set()
            await speech_started.wait()
            return 'answer'
        async def speech(*args):
            self.assertTrue(planning_started.is_set())
            speech_started.set()
        agent.inference.speak.side_effect = speech
        self.assertEqual(await asyncio.wait_for(agent.with_notice(work(), 'Checking.'), 2), 'answer')
        agent.inference.speak.assert_awaited_once()
        self.assertEqual(agent.inference.speak.call_args.args[2], agent.overlay.message)

    async def test_fast_result_skips_notice(self):
        agent = self.agent()
        self.assertEqual(await agent.with_notice(AsyncMock(return_value='ready')(), 'Checking.'), 'ready')
        agent.inference.speak.assert_not_awaited()

    async def test_failed_notice_does_not_fail_planning(self):
        agent = self.agent()
        agent.inference.speak.side_effect = RuntimeError('TTS unavailable')
        async def work():
            await asyncio.sleep(.4)
            return 'ready'
        self.assertEqual(await agent.with_notice(work(), 'Checking.'), 'ready')

    async def test_cancel_cleans_up_planner_and_notice(self):
        agent = self.agent()
        stopped = asyncio.Event()
        async def work():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        task = asyncio.create_task(agent.with_notice(work(), 'Checking.'))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(stopped.is_set())

    async def test_kev_can_discover_then_act_without_large_planner(self):
        agent = self.agent()
        agent.inference.quick_plan.side_effect = [
            {'actions': [{'name': 'desktop_read', 'argument': 'applications'}], 'reply': ''},
            {'actions': [{'name': 'launch_app', 'argument': 'org.kde.dolphin.desktop'}], 'reply': ''}]
        agent.desktop.read.return_value = {'org.kde.dolphin.desktop': 'Dolphin'}
        agent.desktop.prepare.return_value = {'action': {}, 'requires_approval': False}
        agent.desktop.execute.return_value = 'Launch requested.'
        agent.inference.review.return_value = {'decision': 'allow', 'reason': 'Requested'}
        self.assertEqual(await agent.run('Open Dolphin'), 'Launch requested.')
        self.assertEqual(agent.inference.quick_plan.await_count, 2)
        agent.inference.plan.assert_not_awaited()
        agent.inference.speak.assert_not_awaited()
