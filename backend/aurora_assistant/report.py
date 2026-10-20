"""Export a chronological journal and service status without shell parsing."""
import argparse
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
from .approval import control_request

USER_UNITS = ['aurora-assistant.target', 'graphical-session.target', 'aurora-controller.service', 'aurora-tts.service', 'aurora-desktop.service',
              'aurora-voice-overlay.service', 'aurora-inference.service', 'pipewire.service', 'wireplumber.service']
SYSTEM_UNITS = ['aurora-models.service', 'searx.service', 'uwsgi.service']


def run(argv):
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=30)
        return result.stdout, result.stderr, result.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        return '', type(exc).__name__, 1


def journal_command(units, since, user=False):
    return ['journalctl', *(['--user'] if user else []), '--boot', '--since', since,
            '--no-pager', '--output=json', *[arg for unit in units for arg in ('-u', unit)]]


def unit_states(output):
    units = {}
    for block in output.strip().split('\n\n'):
        values = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
        if 'Id' in values:
            units[values['Id']] = values
    return units


def collect(since):
    sections = ['Aurora diagnostic report', 'Revision: ' + os.environ.get('AURORA_REVISION', 'unknown'), 'Collected: ' + datetime.now(timezone.utc).isoformat(),
                'Journal messages may contain personal data, especially with diagnostics.logContent enabled.']
    properties = ('Id,LoadState,UnitFileState,ActiveState,SubState,Result,ConditionResult,AssertResult,'
                  'ExecMainCode,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp,'
                  'ActiveEnterTimestamp,InactiveEnterTimestamp,NRestarts,MainPID,ExecStart,FragmentPath,InvocationID')
    for user, units in ((True, USER_UNITS), (False, SYSTEM_UNITS)):
        status, error, code = run(['systemctl', *(['--user'] if user else []), 'show', *units,
                                   '--property=' + properties])
        sections.extend(['\n' + ('USER' if user else 'SYSTEM') + ' UNIT STATUS', status, error])
        if code:
            sections.append(f'Status query exited with code {code}')
        if user:
            states = unit_states(status)
            controller = states.get('aurora-controller.service', {})
            if controller.get('ActiveState') in ('inactive', 'failed'):
                sections.append('CONTROL UNAVAILABLE: the controller is not running. '
                    'From the configured Plasma user session, run: systemctl --user restart aurora-assistant.target. '
                    'If startup fails, inspect the target, ConditionResult and service results above.')
    sections.append('\nLIVE CONTROLLER EVENTS (bounded metadata; independent of journal)')
    try:
        live = control_request({'command': 'diagnostics'})
        sections.append(json.dumps(live, indent=2))
        service_pid = states.get('aurora-controller.service', {}).get('MainPID')
        if service_pid and service_pid != str(live.get('pid')) and 'pid' in live:
            sections.append('CONTROLLER PID MISMATCH: the control socket belongs to a different process '
                            'than aurora-controller.service. Check for a manually started controller.')
    except (OSError, ValueError) as exc:
        sections.append('Live controller diagnostics unavailable: ' + type(exc).__name__)
    entries = []
    for user, units in ((True, USER_UNITS), (False, SYSTEM_UNITS)):
        output, error, code = run(journal_command(units, since, user))
        if error or code:
            sections.append(f'Journal access ({"user" if user else "system"}, exit {code}): {error.strip()}')
        for line in output.splitlines():
            try:
                row = json.loads(line)
                entries.append(row)
            except ValueError:
                sections.append('Unreadable journal row omitted')
    sections.append('\nMERGED TIMELINE (UTC)')
    for row in sorted(entries, key=lambda row: int(row.get('__REALTIME_TIMESTAMP', 0))):
        stamp = datetime.fromtimestamp(int(row.get('__REALTIME_TIMESTAMP', 0)) / 1e6, timezone.utc).isoformat(timespec='milliseconds')
        unit = row.get('USER_UNIT') or row.get('UNIT') or row.get('_SYSTEMD_USER_UNIT') or row.get('_SYSTEMD_UNIT') or row.get('SYSLOG_IDENTIFIER', '?')
        message = row.get('MESSAGE', '')
        if isinstance(message, list):
            message = bytes(message).decode(errors='replace') if all(type(x) is int and 0 <= x <= 255 for x in message) else str(message)
        sections.append(f'{stamp} {unit} pid={row.get("_PID", "?")} {message}')
    return '\n'.join(filter(None, sections)) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since', default='30 minutes ago')
    parser.add_argument('--clipboard', action='store_true')
    args = parser.parse_args()
    report = collect(args.since)
    if args.clipboard:
        try:
            subprocess.run(['wl-copy'], input=report, text=True, check=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            print(report, end='')
            raise SystemExit('Clipboard unavailable; report printed to stdout: ' + type(exc).__name__)
        print('Aurora report copied to clipboard.', file=sys.stderr)
    else:
        print(report, end='')
