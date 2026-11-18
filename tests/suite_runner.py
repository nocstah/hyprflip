"""Runs compositor suites one after another, each in its own disposable nested session (tests/nested_session.py),
and prints a summary. tests/key_suites.py and tests/release_suites.py name the suites; this module runs them.

A failed suite's session directory is kept for inspection; the others are removed.
"""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

PROJECT = Path(__file__).resolve().parent.parent
SESSION = '{session}'
# A check that passed: the suites print "PASS …", OmaCards' QML runs "qml: PASS …".
PASSED = re.compile(r'^(?:.*qml: )?PASS\b')


@dataclass
class Suite:
    """One nested session and what runs in it."""
    file: str = ''                                    # under tests/, run with the session file and args
    args: list = field(default_factory=list)          # the suite's own arguments
    session: list = field(default_factory=list)       # nested_session.py flags, such as --notify-recorder
    env: dict = field(default_factory=dict)           # for the session only, such as HYPRFLIP_CLOSE_HOOKS
    home: bool = False                                # the session gets a HOME of its own in its directory
    # Commands instead of file: each an argv with {session} for the session file, and the directory it runs in.
    commands: list = field(default_factory=list)


def add_session_options(parser):
    parser.add_argument('--aquamarine', type=Path, help='passed to tests/nested_session.py (NVIDIA, see TESTING.md)')
    parser.add_argument('--render-node', type=Path, help='passed to tests/nested_session.py with --aquamarine')
    parser.add_argument('--start-timeout', type=float, default=90, help='seconds to wait for a session (default 90)')
    parser.add_argument('--timeout', type=float, default=900, help='seconds each suite may take (default 900)')


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


def run(name, suite, options, logs):
    """One suite in a fresh session: 'pass', or why it did not."""
    # The session refuses a directory longer than 18 bytes: /tmp/hfk- and eight characters is 17.
    directory = Path(tempfile.mkdtemp(prefix='hfk-', dir='/tmp'))
    command = [sys.executable, '-u', str(PROJECT / 'tests/nested_session.py'), '--directory', str(directory)]
    if options.aquamarine:
        command += ['--aquamarine', str(options.aquamarine)]
    if options.render_node:
        command += ['--render-node', str(options.render_node)]
    command += suite.session
    env = {**os.environ, **suite.env}
    if suite.home:
        (directory / 'home').mkdir()
        env['HOME'] = str(directory / 'home')
    session_log = logs / f'{name}-session.log'
    suite_log = logs / f'{name}.log'
    with session_log.open('wb') as out:
        session = subprocess.Popen(command, cwd=PROJECT, stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
                                   env=env)
    result = 'pass'
    try:
        deadline = time.monotonic() + options.start_timeout
        while not any(line.startswith('READY ') for line in session_log.read_text(errors='replace').splitlines()):
            if session.poll() is not None or time.monotonic() > deadline:
                result = f'session did not start, see {session_log}'
                return result
            time.sleep(.2)
        file = str(directory / 'session.json')
        steps = suite.commands or [([sys.executable, '-u', str(PROJECT / 'tests' / suite.file), SESSION, *suite.args], PROJECT)]
        print(f'== {name}: ' + ' && '.join(Path(argv[2] if argv[1] == '-u' else argv[1]).name for argv, _ in steps), flush=True)
        code = 0
        with suite_log.open('wb') as out:
            for argv, cwd in steps:
                try:
                    code = subprocess.run([file if part == SESSION else part for part in argv], cwd=cwd, stdout=out,
                                          stderr=subprocess.STDOUT, timeout=options.timeout).returncode
                except subprocess.TimeoutExpired:
                    code = None
                if code != 0:
                    break
        lines = suite_log.read_text(errors='replace').splitlines()
        passed = sum(bool(PASSED.match(line)) for line in lines)
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


def run_all(title, suites, chosen, options, logs):
    """Runs the chosen suites in order and prints the summary under title; the exit status."""
    logs.mkdir(parents=True, exist_ok=True)
    # A session runs in its own process group: a terminated runner still closes it.
    signal.signal(signal.SIGTERM, interrupted)
    results = {}
    try:
        for name in chosen:
            results[name] = run(name, suites[name], options, logs)
    except KeyboardInterrupt:
        print('interrupted', file=sys.stderr)
    width = max(map(len, chosen), default=0)
    print(f'\n{title}:')
    for name in chosen:
        print(f'  {name:{max(width, 10)}} {results.get(name, "not run")}')
    print(f'Logs: {logs}')
    return 0 if all(results.get(name) == 'pass' for name in chosen) else 1
