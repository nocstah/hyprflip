#!/usr/bin/env python3
"""Check prerequisites, build, and install Hyprflip with its guided-setup helper.

One command for a fresh install or an update from this checkout. With --json,
each step is reported as one JSON object per line, for panels such as OmaCards:

  {"event": "step", "id": "check", "title": "...", "status": "running|ok|failed", "detail": "...", "fix": "..."}
  {"event": "done", "ok": true, "version": "0.3.0"}

Nothing here uses sudo. Missing packages are reported with the command to run.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

project = Path(__file__).resolve().parent.parent
# pkg-config module or command -> Arch package that provides it.
PACKAGES = {'cmake': 'cmake', 'ninja': 'ninja', 'pkg-config': 'pkgconf', 'c++': 'gcc', 'git': 'git',
            'python3': 'python', 'hyprland': 'hyprland', 'lua5.4': 'lua', 'glesv2': 'libglvnd'}


class Failed(Exception):
    def __init__(self, detail, fix=''):
        super().__init__(detail)
        self.detail, self.fix = detail, fix


class Reporter:
    def __init__(self, json_lines):
        self.json = json_lines

    def emit(self, **event):
        if self.json:
            print(json.dumps(event), flush=True)
        elif event['event'] == 'step':
            mark = {'running': '…', 'ok': '✓', 'failed': '✗'}[event['status']]
            line = f"{mark} {event['title']}"
            if event.get('detail') and event['status'] != 'running':
                line += f": {event['detail']}"
            print(line, flush=True)
            if event.get('fix'):
                print(f"  Fix: {event['fix']}", flush=True)
        elif event['event'] == 'done':
            if event.get('checked_only'):
                print('Ready to build and install.' if event['ok'] else 'Fix the problem above, then try again.', flush=True)
            else:
                print('Hyprflip is installed.' if event['ok'] else 'Hyprflip was not installed.', flush=True)

    def step(self, id, title, action):
        self.emit(event='step', id=id, title=title, status='running')
        try:
            detail = action() or ''
        except Failed as error:
            self.emit(event='step', id=id, title=title, status='failed', detail=error.detail, fix=error.fix)
            raise
        self.emit(event='step', id=id, title=title, status='ok', detail=detail)
        return detail


def run(*command, timeout=900):
    result = subprocess.run(command, cwd=project, capture_output=True, text=True, timeout=timeout)
    output = (result.stdout + result.stderr).strip()
    return result.returncode, output


def last_lines(text, count=6):
    return '\n'.join(text.strip().splitlines()[-count:])


def required_version():
    match = re.search(r'pkg_check_modules\(HYPRLAND REQUIRED IMPORTED_TARGET hyprland=([\d.]+)\)',
                      (project / 'CMakeLists.txt').read_text())
    return match.group(1)


def plugin_version():
    return re.search(r'project\(hyprflip VERSION ([\d.]+)', (project / 'CMakeLists.txt').read_text()).group(1)


def check():
    missing = [tool for tool in ('cmake', 'ninja', 'pkg-config', 'c++', 'git', 'python3') if not shutil.which(tool)]
    if 'pkg-config' not in missing:
        missing += [module for module in ('lua5.4', 'glesv2', 'hyprland')
                    if subprocess.run(['pkg-config', '--exists', module]).returncode]
    if missing:
        packages = sorted({PACKAGES[name] for name in missing})
        raise Failed('Missing ' + ', '.join(missing), 'sudo pacman -S --needed ' + ' '.join(packages))
    if not shutil.which('hyprctl'):
        raise Failed('hyprctl is not available; run this inside a Hyprland session')
    code, output = run('hyprctl', 'version', '-j')
    if code:
        raise Failed('Hyprland is not responding; run this inside a Hyprland session')
    running = json.loads(output)
    wanted = required_version()
    if running.get('tag', '').lstrip('v') != wanted:
        raise Failed(f"This Hyprflip targets Hyprland {wanted}; you are running {running.get('tag', 'an unknown version')}",
                     'Use the Hyprflip release made for your Hyprland version')
    _, headers = run('pkg-config', '--modversion', 'hyprland')
    if headers.strip() != wanted:
        raise Failed(f'Hyprland headers are {headers.strip()}, but Hyprland {wanted} is running',
                     'Update the hyprland package so its headers match the running compositor, then log in again')
    pins = tomllib.loads((project / 'hyprpm.toml').read_text())['repository']['commit_pins']
    if running.get('commit') not in {hyprland for hyprland, _ in pins}:
        raise Failed(f"Hyprland {running.get('tag')} commit {running.get('commit', '?')[:12]} is not one this source was "
                     'tested against', 'Use the Hyprflip release made for your Hyprland build')
    code, output = run('cmake', '--version')
    version = re.search(r'(\d+)\.(\d+)', output)
    if not version or tuple(map(int, version.groups())) < (3, 25):
        raise Failed('CMake 3.25 or newer is required', 'sudo pacman -S --needed cmake')
    return f"Hyprland {running.get('tag')} with matching headers"


def build():
    code, output = run('cmake', '-S', '.', '-B', 'build', '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=RelWithDebInfo')
    if code:
        raise Failed('CMake could not configure the build:\n' + last_lines(output))
    code, output = run('cmake', '--build', 'build', '-j4')
    if code:
        raise Failed('The build failed:\n' + last_lines(output, 10),
                     'Hyprflip needs a C++26 compiler matching the one Hyprland was built with')
    code, output = run('ctest', '--test-dir', 'build', '--output-on-failure')
    if code:
        raise Failed('The core self-test failed:\n' + last_lines(output))
    return 'Built and self-tested'


def install_core():
    code, output = run(sys.executable, 'scripts/install.py', timeout=300)
    if code:
        raise Failed(last_lines(output))
    kept = re.search(r'Keeping (\d+) open card', output)
    return 'Loaded' + (f'; kept {kept.group(1)} open card(s)' if kept else '')


def install_helper():
    code, output = run(sys.executable, 'scripts/install-setup.py', timeout=300)
    if code:
        raise Failed(last_lines(output))
    return 'Card menus, shortcuts and the OmaCards helper are installed'


def record_commit():
    """Remember which source commit is installed, so panels can offer updates."""
    code, commit = run('git', 'rev-parse', 'HEAD')
    if code or not re.fullmatch(r'[0-9a-f]{40}', commit.strip()):
        return ''
    state = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'hyprflip'
    state.mkdir(parents=True, exist_ok=True)
    temporary = state / 'installed-commit.new'
    temporary.write_text(commit.strip() + '\n')
    temporary.replace(state / 'installed-commit')
    return commit.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--json', action='store_true', help='report each step as one JSON object per line')
    parser.add_argument('--check', action='store_true', help='only check prerequisites')
    parser.add_argument('--core-only', action='store_true', help='skip the guided-setup helper')
    args = parser.parse_args()
    report = Reporter(args.json)
    try:
        report.step('check', 'Check prerequisites', check)
        if not args.check:
            report.step('build', 'Build Hyprflip', build)
            report.step('core', 'Install the plugin', install_core)
            if not args.core_only:
                report.step('helper', 'Install card menus and the OmaCards helper', install_helper)
    except Failed:
        report.emit(event='done', ok=False, checked_only=args.check)
        return 1
    commit = '' if args.check else record_commit()
    report.emit(event='done', ok=True, version=plugin_version(), checked_only=args.check, **({'commit': commit} if commit else {}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
