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
from pathlib import Path
import sys

from suite_runner import PROJECT, Suite, add_session_options, run_all

# The suites, and what each session or command line needs besides the session file.
SUITES = {
    'workflows': Suite('workflows.py'),                                   # --hyprglass below
    'nearby': Suite('nearby_card_workflows.py', session=['--notify-recorder']),
    'setup': Suite('setup_workflows.py'),
    'edit': Suite('edit_workflows.py'),
    'pane': Suite('pane_workflows.py'),                                   # takes --hyprglass too
    'switch': Suite('navigation_switch_workflows.py', session=['--native-cards']),
    # guided setup with a module that claims one of its keys, in a session with its own home
    'claim': Suite('claimed_key_workflows.py', home=True),
}


def suites(hyprglass):
    """The key module suites, with Hyprglass where workflows.py and pane_workflows.py take it."""
    chosen = dict(SUITES)
    if hyprglass:
        for name in ('workflows', 'pane'):
            chosen[name] = Suite(SUITES[name].file, args=['--hyprglass', str(hyprglass)])
    return chosen


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--hyprglass', type=Path, help='hyprglass.so, which workflows.py needs (pane_workflows.py takes it too)')
    add_session_options(parser)
    parser.add_argument('--only', nargs='+', choices=SUITES, help='run only these suites')
    args = parser.parse_args()
    chosen = args.only or list(SUITES)
    if 'workflows' in chosen and not args.hyprglass:
        parser.error('workflows.py needs --hyprglass PATH (or leave it out with --only)')
    if args.hyprglass and not args.hyprglass.is_file():
        parser.error(f'no such file: {args.hyprglass}')
    sys.exit(run_all('Key module suites', suites(args.hyprglass), chosen, args, PROJECT / 'test-results' / 'key-suites'))
