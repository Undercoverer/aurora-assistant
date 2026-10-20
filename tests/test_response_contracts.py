"""Transport contract failures should remain diagnosable and bounded."""
import json
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from aurora_assistant.actions import PlanValidationError
from aurora_assistant.inference import Inference
from aurora_assistant.kev import Kev
from aurora_assistant import telemetry
from aurora_assistant.desktop_bus import DesktopService
from test_desktop_bus import invoke


class ResponseContracts(unittest.IsolatedAsyncioTestCase):
    async def test_bad_completion_envelopes_use_plan_validation_path(self):
        client = Inference({'apps': {}, 'llm': {'url': 'http://127.0.0.1:8008/v1', 'model': 'test'}})
        try:
            for body in ('not json', 'null', '[]', '{}', '{"choices": []}',
                         '{"choices": [{"message": null}]}'):
                with self.subTest(body=body):
                    client.request = AsyncMock(return_value=httpx.Response(200, text=body,
                        request=httpx.Request('POST', 'http://localhost')))
                    with self.assertRaisesRegex(PlanValidationError, 'completion envelope'):
                        await client.plan('test')
        finally:
            await client.close()

    async def test_decisions_must_answer_exact_requested_questions(self):
        for envelope in ({}, {'answers': []}, {'answers': {'other': {}}}, {'answers': None}):
            request = AsyncMock(return_value=httpx.Response(200, json=envelope,
                request=httpx.Request('POST', 'http://localhost')))
            with self.subTest(envelope=envelope), self.assertRaises(ValueError):
                await Kev({}, request).decide('state', {'ready': {'type': 'noul'}})

    async def test_desktop_logs_original_failure_before_dbus_wrapping(self):
        service = DesktopService({'apps': {}, 'commands': {}})
        with patch.object(telemetry, 'failure') as failure:
            with self.assertRaises(Exception):
                await invoke(service, 'Prepare', 'volume', '"not an integer"')
            failure.assert_called_once()
            self.assertIsInstance(failure.call_args.args[1], PlanValidationError)

    def test_error_content_is_opt_in_and_excluded_from_recent_buffer(self):
        secret = 'private URL and transcript'
        with patch.object(telemetry, 'log_content', False), patch.object(telemetry.log, 'info') as log:
            telemetry.failure('test.failure', ValueError(secret))
            self.assertNotIn(secret, log.call_args.args[0])
            telemetry.failure('test.failure', PlanValidationError('Invalid action fields'))
            self.assertEqual(json.loads(log.call_args.args[0])['validation_reason'], 'Invalid action fields')
        with patch.object(telemetry, 'log_content', True), patch.object(telemetry.log, 'info') as log:
            telemetry.failure('test.failure', ValueError(secret))
            self.assertEqual(json.loads(log.call_args.args[0])['error_message'], secret)
            self.assertNotIn('error_message', telemetry.snapshot()['events'][-1])
