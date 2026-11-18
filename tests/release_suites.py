#!/usr/bin/env python3
"""Release check: every compositor suite a release runs, each in its own disposable nested session
(tests/nested_session.py), one after another, and a summary. Run it before every release (CONTRIBUTING.md, Releases)
and record the results in TESTING.md.

It runs this checkout's build (make first), the key module suites of tests/key_suites.py, and, with --omacards,
OmaCards' native panel checks against this checkout's helper. It needs what the nested session needs (TESTING.md,
Running the checks; --aquamarine on NVIDIA) and Hyprglass for workflows.py. --protocol (Hyprland's
wlr-virtual-pointer-unstable-v1.xml) adds the real pointer checks of the cover, fullscreen and close-reason suites;
without it they run without them, and the summary says so. Logs go to test-results/release-suites/. A failed suite's
session directory is kept for inspection; the others are removed. Exit status 0 only when every chosen suite passed.

  python3 tests/release_suites.py --hyprglass ~/.local/share/hyprland-plugins/hyprglass.so \\
      --protocol wlr-virtual-pointer-unstable-v1.xml --omacards ~/code/omacards --aquamarine /path/to/aquamarine/build
"""
import argparse
from pathlib import Path
import sys

import key_suites
from suite_runner import PROJECT, SESSION, Suite, add_session_options, run_all

NOTIFY = ['--notify-recorder']
HOOKS_OFF = {'HYPRFLIP_CLOSE_HOOKS': '0'}


def suites(args):
    pointer = ['--protocol', str(args.protocol)] if args.protocol else []
    chosen = {
        # Updates and removal: cards kept through a reload, and a clean uninstall in a home of its own.
        'install': Suite('install_cards.py', session=NOTIFY),
        'uninstall': Suite('uninstall_session.py', session=NOTIFY, home=True),
        # Restores, with and without the close hooks.
        'restore-cover': Suite('restore_cover_workflows.py', session=NOTIFY),
        'restore-cover-hooks-off': Suite('restore_cover_workflows.py', args=['--hooks-off'], session=NOTIFY, env=HOOKS_OFF),
        # Cards by id, the card helper's unattended requests, and reveal.
        'card-id': Suite('card_id_workflows.py', session=NOTIFY),
        'unattended': Suite('unattended_workflows.py', session=NOTIFY),
        'reveal': Suite('reveal_workflows.py', session=NOTIFY),
        # Covers, fullscreen cards and close reasons, with real pointer checks when --protocol is given.
        'cover': Suite('cover_workflows.py', args=pointer, session=NOTIFY),
        'fullscreen': Suite('fullscreen_workflows.py', args=pointer, session=NOTIFY),
        'close-reason': Suite('close_reason_workflows.py', args=pointer, session=NOTIFY),
        'close-reason-hooks-off': Suite('close_reason_workflows.py', args=['--hooks-off'], session=NOTIFY, env=HOOKS_OFF),
        # Layouts and the older card behaviour.
        'multiface': Suite('multiface_workflows.py', session=NOTIFY),
        'dwindle': Suite('dwindle_workflows.py', session=NOTIFY),
        'floating': Suite('floating_workflows.py', session=NOTIFY),
        'switcher': Suite('switcher_workflows.py', session=NOTIFY),
        'repair': Suite('repair_workflows.py', session=NOTIFY),
        'opening': Suite('opening_workflows.py', session=NOTIFY),
    }
    chosen.update({f'keys-{name}': suite for name, suite in key_suites.suites(args.hyprglass).items()})
    if args.omacards:
        # OmaCards' panel against this checkout: run-native.py then navigation-native.py, in one native-cards session.
        python = sys.executable
        chosen['omacards-panel'] = Suite(session=['--native-cards'], commands=[
            ([python, '-u', 'tests/run-native.py', SESSION, '--backend', str(PROJECT / 'scripts/control.py'), '--dwindle'],
             args.omacards),
            ([python, '-u', 'tests/navigation-native.py', SESSION, '--hyprflip', str(PROJECT)], args.omacards)])
    return chosen


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--hyprglass', type=Path, help='hyprglass.so, which keys-workflows needs')
    parser.add_argument('--protocol', type=Path, help="Hyprland's wlr-virtual-pointer-unstable-v1.xml, for real pointer checks")
    parser.add_argument('--omacards', type=Path, help="an OmaCards checkout, to run its native panel checks")
    add_session_options(parser)
    names = list(suites(argparse.Namespace(protocol=None, hyprglass=None, omacards=Path('.'))))
    parser.add_argument('--only', nargs='+', choices=names, metavar='SUITE', help='run only these suites: ' + ', '.join(names))
    parser.add_argument('--skip', nargs='+', choices=names, metavar='SUITE', default=[], help='leave these suites out')
    args = parser.parse_args()
    for name, path in (('--hyprglass', args.hyprglass), ('--protocol', args.protocol)):
        if path and not path.is_file():
            parser.error(f'{name}: no such file: {path}')
    if args.omacards and not (args.omacards / 'tests/run-native.py').is_file():
        parser.error(f'--omacards: {args.omacards} is not an OmaCards checkout')
    available = suites(args)
    chosen = [name for name in (args.only or available) if name in available and name not in args.skip]
    if 'keys-workflows' in chosen and not args.hyprglass:
        parser.error('keys-workflows needs --hyprglass PATH (or leave it out with --skip keys-workflows)')
    if args.only and 'omacards-panel' in args.only and not args.omacards:
        parser.error('omacards-panel needs --omacards PATH')
    if not (PROJECT / 'build/hyprflip.so').is_file():
        parser.error('build/hyprflip.so is missing: run make first')
    notes = [] if args.protocol else ['cover, fullscreen and close-reason ran without their pointer checks (--protocol)']
    if not args.omacards:
        notes.append("OmaCards' panel checks did not run (--omacards)")
    code = run_all('Release suites', available, chosen, args, PROJECT / 'test-results' / 'release-suites')
    for note in notes:
        print('Note: ' + note)
    sys.exit(code)
