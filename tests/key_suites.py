#!/usr/bin/env python3
"""Release check for the shipped key modules (examples/containers-navigation.lua and
examples/containers-setup.lua): runs every compositor suite that loads them or switches them, each in its own
disposable nested session (tests/nested_session.py), one after another, and prints a summary.

Run it before every release (CONTRIBUTING.md, Releases). It needs what the nested session needs
(TESTING.md, Running the checks; --aquamarine on NVIDIA) and Hyprglass for workflows.py. Logs go to
test-results/key-suites/. A failed suite's session directory is kept for inspection; the others are
removed. Exit status 0 only when every chosen suite passed.
"""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parent.parent
# name: (suite file, what its session or command line needs besides the session file)
SUITES = {
    'workflows': ('workflows.py', 'hyprglass'),
    'nearby': ('nearby_card_workflows.py', 'notify-recorder'),
    'setup': ('setup_workflows.py', None),
    'edit': ('edit_workflows.py', None),
    'pane': ('pane_workflows.py', None),
    'switch': ('navigation_switch_workflows.py', 'native-cards'),
}

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('--hyprglass', type=Path, help='hyprglass.so, which workflows.py needs (pane_workflows.py takes it too)')
parser.add_argument('--aquamarine', type=Path, help='passed to tests/nested_session.py (NVIDIA, see TESTING.md)')
parser.add_argument('--render-node', type=Path, help='passed to tests/nested_session.py with --aquamarine')
parser.add_argument('--only', nargs='+', choices=SUITES, help='run only these suites')
parser.add_argument('--start-timeout', type=float, default=90, help='seconds to wait for a session (default 90)')
parser.add_argument('--timeout', type=float, default=900, help='seconds each suite may take (default 900)')
args = parser.parse_args()
chosen = args.only or list(SUITES)
if 'workflows' in chosen and not args.hyprglass:
    parser.error('workflows.py needs --hyprglass PATH (or leave it out with --only)')
if args.hyprglass and not args.hyprglass.is_file():
    parser.error(f'no such file: {args.hyprglass}')
logs = PROJECT / 'test-results' / 'key-suites'
logs.mkdir(parents=True, exist_ok=True)


def stop(session):
    """Closes a nested session as Ctrl+C in its launcher does, which ends its compositor and clients."""
    if session.poll() is not None:
        return
    session.send_signal(signal.SIGINT)
    try:
        session.wait(timeout=30)
    except subprocess.TimeoutExpired:
        session.terminate()
        try:
            session.wait(timeout=10)
        except subprocess.TimeoutExpired:
            session.kill()
            session.wait()


def run(name):
    """One suite in a fresh session: 'pass', or why it did not."""
    file, needs = SUITES[name]
    # The session refuses a directory longer than 18 bytes: /tmp/hfk- and eight characters is 17.
    directory = Path(tempfile.mkdtemp(prefix='hfk-', dir='/tmp'))
    command = [sys.executable, '-u', str(PROJECT / 'tests/nested_session.py'), '--directory', str(directory)]
    if args.aquamarine:
        command += ['--aquamarine', str(args.aquamarine)]
    if args.render_node:
        command += ['--render-node', str(args.render_node)]
    if needs == 'notify-recorder':
        command.append('--notify-recorder')
    elif needs == 'native-cards':
        command.append('--native-cards')
    session_log = logs / f'{name}-session.log'
    suite_log = logs / f'{name}.log'
    with session_log.open('wb') as out:
        session = subprocess.Popen(command, cwd=PROJECT, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    result = 'pass'
    try:
        deadline = time.monotonic() + args.start_timeout
        while not any(line.startswith('READY ') for line in session_log.read_text(errors='replace').splitlines()):
            if session.poll() is not None or time.monotonic() > deadline:
                result = f'session did not start, see {session_log}'
                return result
            time.sleep(.2)
        suite = [sys.executable, '-u', str(PROJECT / 'tests' / file), str(directory / 'session.json')]
        if args.hyprglass and name in ('workflows', 'pane'):
            suite += ['--hyprglass', str(args.hyprglass)]
        print(f'== {name}: {file}', flush=True)
        with suite_log.open('wb') as out:
            try:
                code = subprocess.run(suite, cwd=PROJECT, stdout=out, stderr=subprocess.STDOUT, timeout=args.timeout).returncode
            except subprocess.TimeoutExpired:
                code = None
        lines = suite_log.read_text(errors='replace').splitlines()
        passed = sum(line.startswith('PASS') for line in lines)
        if code == 0:
            print(f'   {passed} checks passed', flush=True)
        else:
            result = 'timed out' if code is None else f'exit {code}'
            print('\n'.join('   ' + line for line in lines[-25:]), flush=True)
        return result
    finally:
        stop(session)
        if result == 'pass':
            shutil.rmtree(directory, ignore_errors=True)
        else:
            print(f'   session directory kept: {directory}', flush=True)


def interrupted(signum, frame):
    raise KeyboardInterrupt


# A session runs in its own process group: a terminated runner still closes it.
signal.signal(signal.SIGTERM, interrupted)
results = {}
try:
    for name in chosen:
        results[name] = run(name)
except KeyboardInterrupt:
    print('interrupted', file=sys.stderr)
print('\nKey module suites:')
for name in chosen:
    print(f'  {name:10} {results.get(name, "not run")}')
print(f'Logs: {logs}')
sys.exit(0 if all(results.get(name) == 'pass' for name in chosen) else 1)
