#!/usr/bin/env python3
"""Run saved-card workflows across two disposable compositor processes."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--results', type=Path, required=True)
parser.add_argument('--engine', type=Path)
args = parser.parse_args()
assert args.results.resolve().is_relative_to('/tmp') and not args.results.exists()
args.results.mkdir(parents=True)
project = Path(__file__).resolve().parent.parent
for phase in ('save', 'restore'):
    root = Path(tempfile.mkdtemp(prefix='hf-s', dir='/tmp'))
    with (args.results / (phase + '-launcher.log')).open('w') as log:
        launcher = subprocess.Popen(['python', str(project / 'tests/nested_session.py'), '--directory', str(root)], stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 25
            while not (root / 'session.json').exists():
                assert launcher.poll() is None, 'Nested launcher failed; see ' + str(root)
                if time.monotonic() >= deadline: raise TimeoutError(str(root))
                time.sleep(.1)
            # The connection file precedes the launcher's two fixture windows.
            time.sleep(1.5)
            command = ['python', str(project / 'tests/saved_workflows.py'), str(root / 'session.json'),
                       '--state-dir', str(args.results), '--phase', phase]
            if args.engine: command += ['--engine', str(args.engine)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=150)
            (args.results / (phase + '-workflow.log')).write_text(result.stdout + result.stderr)
            print(result.stdout, end='', flush=True)
            assert result.returncode == 0, result.stderr
        finally:
            launcher.terminate(); launcher.wait(timeout=15)
    (args.results / (phase + '-session.txt')).write_text(str(root))
print('PASS saved cards survive a real compositor process restart', flush=True)
