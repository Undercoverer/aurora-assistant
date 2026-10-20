import json
import logging
import unittest
from unittest.mock import patch

from aurora_assistant import telemetry
from aurora_assistant.approval import Approval
from aurora_assistant.report import collect


class LiveDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        with telemetry._recent_lock:
            telemetry._recent.clear()

    def test_events_survive_disabled_logging_without_transcript_content(self):
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            telemetry.event('transcript.final', text='private words', characters=13)
            result = Approval().dispatch({'command': 'diagnostics'})
        finally:
            logging.disable(previous)
        self.assertEqual(result['events'][-1]['event'], 'transcript.final')
        self.assertNotIn('private words', json.dumps(result))

    def test_buffer_fits_control_response_limit(self):
        with patch.object(telemetry.log, 'info'):
            for _ in range(200):
                telemetry.event('test', large='x' * 10000)
        result = telemetry.snapshot()
        self.assertEqual(len(result['events']), 128)
        self.assertLess(len(json.dumps(result).encode()), 262144)

    def test_failure_keeps_status_and_location_without_response_body(self):
        import httpx
        response = httpx.Response(503, request=httpx.Request('GET', 'http://localhost'),
                                  text='private generated content')
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            telemetry.failure('request.failed', exc)
        row = telemetry.snapshot()['events'][-1]
        self.assertEqual(row['http_status'], 503)
        self.assertTrue(row['frames'])
        self.assertNotIn('private generated content', json.dumps(row))

    def test_report_includes_events_without_journal_and_detects_other_controller(self):
        status = 'Id=aurora-controller.service\nActiveState=active\nMainPID=123\n'
        with patch('aurora_assistant.report.run', side_effect=[
                (status, '', 0), ('', '', 0), ('', '', 0), ('', '', 0)]), patch(
                'aurora_assistant.report.control_request', return_value={
                    'pid': 456, 'events': [{'event': 'request.failed', 'error_type': 'ValueError'}]}):
            report = collect('5 minutes ago')
        self.assertIn('request.failed', report)
        self.assertIn('CONTROLLER PID MISMATCH', report)

    def test_older_controller_error_remains_visible(self):
        with patch('aurora_assistant.report.run', return_value=('', '', 0)), patch(
                'aurora_assistant.report.control_request', return_value={'error': 'Invalid approval command'}):
            self.assertIn('Invalid approval command', collect('5 minutes ago'))
