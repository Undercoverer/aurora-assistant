import json
import unittest
from unittest.mock import patch
from aurora_assistant.approval import main
from aurora_assistant.report import collect, USER_UNITS


class InactiveServiceTests(unittest.TestCase):
    def test_missing_control_socket_gives_start_command(self):
        with patch('sys.argv', ['aurora-control', 'capabilities']), patch(
                'aurora_assistant.approval.control_request', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(SystemExit, 'systemctl --user restart aurora-assistant.target'):
                main()

    def test_denied_control_socket_does_not_suggest_sudo(self):
        with patch('sys.argv', ['aurora-control', 'pending']), patch(
                'aurora_assistant.approval.control_request', side_effect=PermissionError):
            with self.assertRaisesRegex(SystemExit, 'without sudo'):
                main()

    def test_report_includes_targets_provisioner_and_stop_evidence(self):
        status = 'Id=aurora-controller.service\nActiveState=inactive\nExecMainCode=2\nExecMainStatus=15\n\nId=aurora-assistant.target\nActiveState=inactive\n'
        row = {'__REALTIME_TIMESTAMP': '1000000', 'UNIT': 'aurora-models.service',
               '_SYSTEMD_UNIT': 'init.scope', 'MESSAGE': 'Finished provisioning'}
        with patch('aurora_assistant.report.run', side_effect=[
                (status, '', 0), ('Id=aurora-models.service\nResult=success', '', 0),
                ('', '', 0), (json.dumps(row), '', 0)]) as run:
            report = collect('10 minutes ago')
        self.assertIn('graphical-session.target', USER_UNITS)
        self.assertIn('CONTROL UNAVAILABLE', report)
        self.assertIn('SYSTEM UNIT STATUS', report)
        self.assertIn('aurora-models.service pid=? Finished provisioning', report)
        self.assertIn('ExecMainCode', run.call_args_list[0].args[0][-1])
