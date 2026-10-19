"""Export a chronological journal and service status without shell parsing."""
import argparse
from datetime import datetime, timezone
import json
import os
import subprocess
import sys

USER_UNITS = ['aurora-controller.service', 'aurora-tts.service', 'aurora-desktop.service',
              'aurora-voice-overlay.service', 'aurora-kev.service', 'pipewire.service', 'wireplumber.service']
SYSTEM_UNITS = ['aurora-models.service', 'ollama.service', 'searx.service', 'uwsgi.service']


def run(argv):
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=30)
        return result.stdout, result.stderr, result.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        return '', type(exc).__name__, 1


def journal_command(units, since, user=False):
    return ['journalctl', *(['--user'] if user else []), '--boot', '--since', since,
            '--no-pager', '--output=json', *[arg for unit in units for arg in ('-u', unit)]]


def collect(since):
    sections = ['Aurora diagnostic report', 'Revision: ' + os.environ.get('AURORA_REVISION', 'unknown'), 'Collected: ' + datetime.now(timezone.utc).isoformat(),
                'Journal messages may contain personal data, especially with diagnostics.logContent enabled.']
    status, error, _ = run(['systemctl', '--user', 'show', *USER_UNITS,
        '--property=Id,ActiveState,SubState,ExecMainStatus,NRestarts,ExecStart,FragmentPath'])
    sections.extend(['\nUSER SERVICE STATUS', status, error])
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
        unit = row.get('_SYSTEMD_USER_UNIT') or row.get('_SYSTEMD_UNIT') or row.get('SYSLOG_IDENTIFIER', '?')
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
