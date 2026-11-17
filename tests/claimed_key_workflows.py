#!/usr/bin/env python3
"""A module that claims one of Hyprflip's keys (hyprflip_claimed_keys) keeps it through guided setup, in a disposable
compositor: install-setup.py leaves the key to it whether the module loads after Hyprflip's modules or before them,
the shortcut editor shows the key with its owner and does not move it, a foreign key without a claim still stops
guided setup before it writes anything, and taking the module out gives Hyprflip its key back.

Start the session with its own home, which the compositor's hyprflip.lua loads the plugin from:

  HOME=/tmp/hf-claim/home python3 tests/nested_session.py --directory /tmp/hf-claim [--aquamarine /tmp/aq/build]
  python3 tests/claimed_key_workflows.py /tmp/hf-claim/session.json
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from control import environment

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import shortcuts
import workflow as w

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument('session', type=Path)
args = parser.parse_args()
root = args.session.resolve().parent
home = root / 'home'
config = root / 'config/hypr'
user = config / 'hyprland.lua'  # the configuration the installers edit, which the session's own loads
ORIGINAL = '-- disposable claimed-key test configuration\nhl.config({ general = { gaps_in = 7 } })\n'
OWNER, OWN = 'Test manager', 'Test manager: its own card key'
CLAIM = f'''hyprflip_claimed_keys = hyprflip_claimed_keys or {{}}
hyprflip_claimed_keys["SUPER + CTRL + ALT + O"] = "{OWNER}"
'''
BIND = f'''hl.unbind("SUPER + CTRL + ALT + O")
hl.bind("SUPER + CTRL + ALT + O", function() end, {{ description = "{OWN}" }})
'''
claimer, unclaimed = config / 'claimer.lua', config / 'unclaimed.lua'
env = {**environment(args.session), 'HOME': str(home), 'XDG_CONFIG_HOME': str(root / 'config'),
       'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
ipc = w.Hyprctl(env)
session_config = root / 'hyprland.lua'
original_session = session_config.read_text()
checks, failed = [], []


def check(message, body):
    try:
        body()
    except Exception as error:
        failed.append(message)
        print('FAIL', message, repr(error), flush=True)
    else:
        checks.append(message)
        print('PASS', message, flush=True)


def run(script, *arguments, ok=True):
    result = subprocess.run([sys.executable, str(project / 'scripts' / script), *arguments], env=env,
                            capture_output=True, text=True, timeout=180)
    if ok:
        assert result.returncode == 0, (script, result.stdout, result.stderr)
    return result


def reload():
    ipc.call('reload')
    assert not ipc.call('configerrors'), ipc.call('configerrors')


def on_o():
    return [b.get('description', '') for b in ipc.data('-j', 'binds') if b['modmask'] == 76 and b['key'].lower() == 'o']


def describe(key):
    return [b.get('description', '') for b in ipc.data('-j', 'binds') if b['modmask'] == 76 and b['key'].lower() == key]


def with_lines(*lines):
    """The user's configuration with only Hyprflip's own lines kept, and these added at the end."""
    kept = [line for line in user.read_text().splitlines() if 'claimer.lua' not in line and 'unclaimed.lua' not in line]
    user.write_text('\n'.join(kept + list(lines)) + '\n')


try:
    assert (home / '.local').resolve().is_relative_to(Path('/tmp')), home
    config.mkdir(parents=True, exist_ok=True)
    user.write_text(ORIGINAL)
    claimer.write_text(CLAIM + BIND)
    unclaimed.write_text(BIND)
    session_config.write_text(original_session + f'dofile({json.dumps(str(user))})\n')
    reload()
    run('install.py')
    reload()
    out = run('install-setup.py').stdout
    assert 'Guided setup installed' in out and on_o() == ['Hyprflip: unfold, fold or create a card'], (out, on_o())
    claim_line = f'dofile({json.dumps(str(claimer))})'

    def after_hyprflip():
        with_lines(claim_line)
        reload()
        assert on_o() == [OWN], on_o()
        out = run('install-setup.py').stdout
        assert f'Super+Ctrl+Alt+O: left to {OWNER}, which claims it.' in out, out
        assert user.read_text().rstrip().endswith(claim_line), user.read_text()
        assert on_o() == [OWN], on_o()
        assert describe('c') == ['Hyprflip: edit card'], describe('c')
    check('a module that claims Super+Ctrl+Alt+O after Hyprflip\'s modules keeps it through guided setup, and the '
          'other keys stay Hyprflip\'s', after_hyprflip)

    def editor():
        rows = {r['id']: r for r in shortcuts.snapshot(ipc)['rows']}
        assert (rows['create']['shortcut'], rows['create']['owner'], rows['create']['editable']) == \
            ('Super+Ctrl+Alt+O', OWNER, False), rows['create']
        assert rows['edit']['editable'] and 'owner' not in rows['edit'], rows['edit']
        for ident, key, message in (('create', 'F9', f'{OWNER} sets this shortcut'), ('edit', 'O', 'is used by ' + OWN)):
            try:
                shortcuts.save(ipc, ident, 76, key)
            except w.SetupError as error:
                assert message in str(error), error
            else:
                raise AssertionError(f'{ident} moved to {key}')
        assert on_o() == [OWN] and describe('c') == ['Hyprflip: edit card'], (on_o(), describe('c'))
        reply = ipc.call('repl', 'return require("hypr.hyprflip-shortcuts").configure("edit", 76, "O")')
        assert reply == 'false' and on_o() == [OWN], (reply, on_o())
    check('the shortcut editor shows the claimed key with its owner, and neither moves it nor moves another action '
          'onto it', editor)

    def before_hyprflip():
        text = user.read_text().replace(claim_line + '\n', '')
        user.write_text(claim_line + '\n' + text)
        reload()
        assert on_o() == [OWN], on_o()
        run('install-setup.py')
        assert user.read_text().startswith(claim_line), user.read_text()[:200]
        assert on_o() == [OWN], on_o()
        assert describe('c') == ['Hyprflip: edit card'], describe('c')
    check('a claim made before Hyprflip\'s modules load keeps Hyprflip from binding the key at all, through guided '
          'setup too', before_hyprflip)

    def foreign_key_without_claim():
        with_lines(f'dofile({json.dumps(str(unclaimed))})')
        reload()
        before = {path: path.read_bytes() for path in config.glob('*.lua')}
        result = run('install-setup.py', ok=False)
        assert result.returncode and 'Super+Ctrl+Alt+O is assigned to another action' in result.stdout + result.stderr, \
            (result.stdout, result.stderr)
        assert {path: path.read_bytes() for path in config.glob('*.lua')} == before
    check('a foreign key without a claim still stops guided setup before it writes anything', foreign_key_without_claim)

    def module_taken_out():
        with_lines()
        reload()
        assert on_o() == ['Hyprflip: unfold, fold or create a card'], on_o()
        out = run('install-setup.py').stdout
        assert 'left to' not in out and on_o() == ['Hyprflip: unfold, fold or create a card'], (out, on_o())
        row = next(r for r in shortcuts.snapshot(ipc)['rows'] if r['id'] == 'create')
        assert row['editable'] and 'owner' not in row, row
    check('taking the claiming module out gives Hyprflip its key back, editable again', module_taken_out)
finally:
    run('uninstall.py', '--yes', ok=False)
    session_config.write_text(original_session)
    try:
        ipc.call('reload')
    except Exception:
        pass

print(json.dumps({'passed': checks, 'failed': failed}))
sys.exit(1 if failed else 0)
