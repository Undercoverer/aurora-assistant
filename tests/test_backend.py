import asyncio
import copy
import unittest
from unittest.mock import AsyncMock, patch
from aurora_assistant.actions import validate, Executor
from aurora_assistant.config import local_url
from aurora_assistant.controller import Controller

APPS = {"files": "org.kde.dolphin.desktop"}


class ValidationTests(unittest.TestCase):
    def test_reject_all_before_execution(self):
        bad = [
            {"name": "volume", "argument": True},
            {"name": "volume", "argument": 101},
            {"name": "volume", "argument": -1},
            {"name": "volume", "argument": 20.5},
            {"name": "mute", "argument": 1},
            {"name": "shell", "argument": "touch /tmp/owned"},
            {"name": "open_app", "argument": "files; touch /tmp/owned"},
            {"name": "media", "argument": "--all-players"},
            {"name": "media", "argument": "play", "extra": "x"},
            {"name": "open_app", "argument": []},
        ]
        for action in bad:
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate({"actions": [{"name": "volume", "argument": 10}, action], "reply": "ok"}, APPS)

    def test_valid_actions(self):
        for name, arg in [("volume", 0), ("volume", 100), ("mute", False), ("media", "next"), ("open_app", "files")]:
            result, _ = validate({"actions": [{"name": name, "argument": arg}], "reply": ""}, APPS)
            self.assertEqual(result[0].argument, arg)

    def test_envelope_rejected(self):
        for plan in [{}, {"actions": [], "reply": 1}, {"actions": [], "reply": "x" * 1001},
                     {"actions": [], "reply": "", "extra": True}, {"actions": [None] * 5, "reply": ""}]:
            with self.assertRaises(ValueError):
                validate(plan, APPS)

    def test_local_urls(self):
        for value in ["http://127.0.0.1:7788/v1", "http://[::1]:7788/v1"]:
            self.assertEqual(local_url(value), value)
        for value in ["https://example.org/v1", "http://localhost/v1", "http://127.0.0.1.evil.org", "http://user@127.0.0.1", "http://192.168.1.1", "file:///tmp/x"]:
            with self.assertRaises((ValueError, TypeError)):
                local_url(value)


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.overlay = AsyncMock()
        self.inference = AsyncMock()
        self.executor = AsyncMock()
        self.controller = Controller(self.overlay, self.inference, self.executor, APPS)

    async def test_no_action_for_invalid_plan(self):
        self.inference.plan.return_value = {"actions": [{"name": "shell", "argument": "anything"}], "reply": "Done"}
        with patch("aurora_assistant.controller.asyncio.sleep", new=AsyncMock()):
            await self.controller.handle("test")
        self.executor.execute.assert_not_called()
        self.overlay.reset.assert_awaited_once()

    async def test_reply_uses_executor_result(self):
        self.inference.plan.return_value = {"actions": [{"name": "volume", "argument": 30}], "reply": "Invented success"}
        self.executor.execute.return_value = "Volume set to 30 percent."
        with patch("aurora_assistant.controller.asyncio.sleep", new=AsyncMock()):
            await self.controller.handle("volume thirty")
        self.assertEqual(self.inference.speak.call_args.args[0], "Volume set to 30 percent.")

    async def test_partial_failure_stops_later_actions(self):
        self.inference.plan.return_value = {"actions": [{"name": "media", "argument": "next"}] * 3, "reply": "Done"}
        self.executor.execute.side_effect = ["First completed.", RuntimeError(), "Must not run"]
        with patch("aurora_assistant.controller.asyncio.sleep", new=AsyncMock()):
            await self.controller.handle("next")
        self.assertEqual(self.executor.execute.await_count, 2)
        self.assertNotIn(unittest.mock.call("success"), self.overlay.state.call_args_list)
        self.assertIn("First completed.", self.inference.speak.call_args.args[0])

    async def test_cancel_resets_overlay(self):
        self.inference.plan.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.controller.handle("test")
        self.overlay.reset.assert_awaited_once()

    async def test_revisions_replace_and_busy_drops_events(self):
        self.controller.accept_events = True
        self.controller.event("partial", "turn on")
        self.controller.event("partial", "turn off")
        self.assertEqual(self.controller.pending, {"partial": "turn off"})
        self.controller.accept_events = False
        self.controller.event("partial", "stale")
        self.assertEqual(self.controller.pending["partial"], "turn off")

    async def test_executor_uses_fixed_argv(self):
        runner = AsyncMock()
        executor = Executor(APPS, {"wpctl": "/bin/wpctl", "playerctl": "/bin/playerctl", "gtk-launch": "/bin/gtk-launch"}, runner)
        actions, _ = validate({"actions": [{"name": "open_app", "argument": "files"}], "reply": ""}, APPS)
        await executor.execute(actions[0])
        runner.assert_awaited_once_with(["/bin/gtk-launch", "org.kde.dolphin.desktop"])


if __name__ == "__main__":
    unittest.main()
