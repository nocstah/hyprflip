#!/usr/bin/env python3
"""Release Hyprflip: the release commit, its tag and the hyprpm pin, in one command.

  python3 scripts/release.py 0.3.0-rc.27 [--body FILE] [--trailer TEXT]... [--date YYYY-MM-DD] [--dry-run] [--no-test]

Before it changes anything it checks that the tracked files are clean, the tag is new, CHANGELOG.md has an
Unreleased section with entries, and TESTING.md has a heading naming the version (the release checks are
recorded first). Then:

1. CHANGELOG.md: "## Unreleased" becomes "## <version> — <date>".
2. README.md: the preview line names the version; docs/BETA.md's links and clone command too. The version's
   TESTING.md section ends with the commit it was released from.
3. The unit tests run (--no-test skips them).
4. Commit "Release Hyprflip <version>" (the body from --body), then the lightweight tag v<version>.
5. hyprpm.toml pins the targeted Hyprland commit to the tagged commit: commit "Pin Hyprland <x.y.z> to <version>".

Nothing is pushed. It prints the push and GitHub release commands. --dry-run prints what would change. --trailer
adds a trailer, such as "Co-Authored-By: Name <address>", to both commits; repeat it for more.
"""
import argparse
import datetime
import difflib
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r'\d+\.\d+\.\d+(?:-rc\.\d+)?')


class Refused(Exception):
    pass


def git(*args, check=True):
    result = subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True, text=True)
    if check and result.returncode:
        raise Refused(f'git {" ".join(args)}: {result.stderr.strip() or result.stdout.strip()}')
    return result.stdout.strip()


def once(text, old, new, name):
    if text.count(old) != 1:
        raise Refused(f'{name}: expected "{old.strip()}" once, found it {text.count(old)} times')
    return text.replace(old, new, 1)


def release_edits(version, previous, date, head):
    """The release commit's files, as they will read: {relative path: (old, new)}."""
    edits = {}
    changelog = (ROOT / 'CHANGELOG.md').read_text()
    section = re.search(r'^## Unreleased\n(.*?)(?=^## |\Z)', changelog, re.M | re.S)
    if not section or not re.search(r'^- ', section.group(1), re.M):
        raise Refused('CHANGELOG.md has no "## Unreleased" section with entries')
    edits['CHANGELOG.md'] = (changelog, once(changelog, '## Unreleased\n', f'## {version} — {date}\n', 'CHANGELOG.md'))
    testing = (ROOT / 'TESTING.md').read_text()
    heading = re.search(rf'^## .*\b{re.escape(version)}\b.*\n', testing, re.M)
    if not heading:
        raise Refused(f'TESTING.md has no heading naming {version}: record the release checks first')
    following = re.search(r'^## ', testing[heading.end():], re.M)
    end = heading.end() + following.start() if following else len(testing)
    section = testing[heading.end():end].rstrip('\n')
    note = (f'Released from {head}. The release commit changes only the changelog, the\n'
            'README, the beta guide and this note.')
    edits['TESTING.md'] = (testing, testing[:heading.end()] + section + '\n\n' + note + '\n' +
                           ('\n' + testing[end:] if following else ''))
    readme = (ROOT / 'README.md').read_text()
    edits['README.md'] = (readme, once(readme, f'**{previous} preview**', f'**{version} preview**', 'README.md'))
    beta = (ROOT / 'docs/BETA.md').read_text()
    if previous not in beta:
        raise Refused(f'docs/BETA.md does not name {previous}')
    edits['docs/BETA.md'] = (beta, beta.replace(previous, version))
    return edits


def pin_edit(commit):
    """hyprpm.toml with its last pin row's plugin commit set to commit, and the Hyprland version CMake targets."""
    toml = (ROOT / 'hyprpm.toml').read_text()
    rows = list(re.finditer(r'\["([0-9a-f]{40})", "([0-9a-f]{40})"\]', toml))
    if not rows:
        raise Refused('hyprpm.toml has no commit pin')
    last = rows[-1]
    hyprland = re.search(r'hyprland=(\d+\.\d+\.\d+)', (ROOT / 'CMakeLists.txt').read_text())
    if not hyprland:
        raise Refused('CMakeLists.txt does not say which Hyprland it targets')
    new = toml[:last.start(2)] + commit + toml[last.end(2):]
    return toml, new, hyprland.group(1)


def show(path, old, new):
    sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f'a/{path}', f'b/{path}'))


def commit(message, paths, trailers=()):
    git('add', '--', *paths)
    git('commit', '--quiet', '-m', message, *(arg for trailer in trailers for arg in ('--trailer', trailer)))
    return git('rev-parse', 'HEAD')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('version', help='such as 0.3.0-rc.27')
    parser.add_argument('--body', type=Path, help="the release commit's message body, from this file")
    parser.add_argument('--trailer', action='append', default=[], help='a trailer for both commits, such as Co-Authored-By: …')
    parser.add_argument('--date', default=datetime.date.today().isoformat(), help='the date in the changelog heading')
    parser.add_argument('--dry-run', action='store_true', help='print what would change, and change nothing')
    parser.add_argument('--no-test', action='store_true', help='skip the unit tests')
    args = parser.parse_args()
    try:
        version = args.version.removeprefix('v')
        if not VERSION.fullmatch(version):
            raise Refused(f'{args.version} is not a version such as 0.3.0-rc.27')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.date):
            raise Refused(f'{args.date} is not a date such as 2026-11-18')
        tag = 'v' + version
        if git('rev-parse', '--verify', '--quiet', f'refs/tags/{tag}', check=False):
            raise Refused(f'the tag {tag} exists already')
        if git('status', '--porcelain', '--untracked-files=no'):
            raise Refused('commit or stash the changes to tracked files first')
        previous = git('describe', '--tags', '--abbrev=0', '--match', 'v[0-9]*').removeprefix('v')
        edits = release_edits(version, previous, args.date, git('rev-parse', '--short=7', 'HEAD'))
        body = args.body.read_text().strip() if args.body else ''
        if args.dry_run:
            for path, (old, new) in edits.items():
                show(path, old, new)
            print(f'\nWould commit "Release Hyprflip {version}", tag {tag} on it, then pin hyprpm.toml to that commit.')
            return 0
        for path, (_, new) in edits.items():
            (ROOT / path).write_text(new)
        if not args.no_test:
            tests = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', '*_test.py'],
                                   cwd=ROOT, capture_output=True, text=True)
            if tests.returncode:
                for path, (old, _) in edits.items():
                    (ROOT / path).write_text(old)
                raise Refused('the unit tests fail; nothing was committed:\n' + tests.stderr[-2000:])
        released = commit(f'Release Hyprflip {version}' + (f'\n\n{body}' if body else ''), list(edits), args.trailer)
        git('tag', tag, released)
        old, new, hyprland = pin_edit(released)
        (ROOT / 'hyprpm.toml').write_text(new)
        pinned = commit(f'Pin Hyprland {hyprland} to {version}', ['hyprpm.toml'], args.trailer)
    except Refused as error:
        print(f'Not released: {error}', file=sys.stderr)
        return 1
    print(f'Released Hyprflip {version}: {tag} is {released}; hyprpm.toml pins it in {pinned[:7]}.')
    print('Nothing is pushed. To publish it:')
    print(f'  git push origin HEAD:main && git push origin {tag}')
    print(f'  gh release create {tag}{" --prerelease" if "-rc." in version else ""} --verify-tag '
          f'--title "Hyprflip {version}" --notes-file <notes>')
    print(f'Then pin OmaCards to it: python3 tools/release.py pin {tag}  (in the omacards checkout)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
