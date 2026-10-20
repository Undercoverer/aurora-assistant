"""Migration instrumentation contracts; no model or desktop service required."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from aurora_assistant import telemetry
from aurora_assistant.agent import SettingsAgent
from aurora_assistant.controller import Controller


class DurationTests(unittest.TestCase):
    def test_duration_has_units_and_turn_without_content(self):
        token = telemetry.new_turn()
        try:
            with patch.object(telemetry, "monotonic", side_effect=[1, 1.025, 2]):
                with telemetry.duration("test.duration"):
                    pass
            row = telemetry.snapshot()["events"][-1]
            self.assertEqual(row["value"], 25)
            self.assertEqual(row["unit"], "ms")
            self.assertEqual(row["completion"], "returned")
            self.assertEqual(row["turn"], telemetry.turn_id.get())
            self.assertNotIn("text", row)
        finally:
            telemetry.turn_id.reset(token)

    def test_cancel_is_recorded_and_propagated(self):
        with patch.object(telemetry, "event") as event:
            with self.assertRaises(asyncio.CancelledError):
                with telemetry.duration("test.duration"):
                    raise asyncio.CancelledError()
        self.assertEqual(event.call_count, 1)
        self.assertEqual(event.call_args.kwargs["completion"], "raised")


class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_controller_keeps_turn_id_until_timing_is_emitted(self):
        controller = Controller(AsyncMock(), AsyncMock(), AsyncMock(), {})
        controller._handle = AsyncMock(side_effect=asyncio.CancelledError())
        previous = telemetry.turn_id.get()
        with self.assertRaises(asyncio.CancelledError):
            await controller.handle("private transcript")
        rows = [r for r in telemetry.snapshot()["events"]
                if r["event"] == "turn.end_to_end_ms"]
        self.assertTrue(rows[-1]["turn"])
        self.assertEqual(rows[-1]["completion"], "raised")
        self.assertEqual(telemetry.turn_id.get(), previous)

    def make_agent(self):
        inference, desktop, approval, overlay = [AsyncMock() for _ in range(4)]
        agent = SettingsAgent({"apps": {}}, inference, desktop, approval, overlay)
        agent._review = AsyncMock(return_value={"decision": "allow"})
        return agent

    async def test_expired_plan_is_logged_without_execution(self):
        agent = self.make_agent()
        with patch("aurora_assistant.agent.event") as event:
            await agent._execute_plan("private request", [{"expires_at": -1}])
        event.assert_any_call("apply.failure.reason", reason="expired", completed_actions=0)
        agent.desktop.execute.assert_not_awaited()

    async def test_partial_failure_logs_count_and_stops(self):
        agent = self.make_agent()
        agent.desktop.execute.side_effect = ["Completed.", ValueError("private value")]
        steps = [{"requires_approval": False, "action": {"name": "theme"}} for _ in range(3)]
        with patch("aurora_assistant.agent.failure") as failure:
            await agent._execute_plan("private request", steps)
        self.assertEqual(agent.desktop.execute.await_count, 2)
        self.assertTrue(agent.failed)
        self.assertEqual(failure.call_args.kwargs,
                         {"reason": "execution_error", "completed_actions": 1})


if __name__ == "__main__":
    unittest.main()
