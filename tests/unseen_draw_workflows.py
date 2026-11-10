#!/usr/bin/env python3
"""Apps given another size while out of sight come into view drawn at it.

Hyprland tells an app to draw (a frame callback) when it draws that app, or on a frame with nothing to draw. An
app resized where it does not draw, on the side its card hides or waiting unseen to slide in, keeps its last
picture at its old size: it comes into view that way, the background showing where the picture no longer reaches,
until it draws again. An app that draws every frame (the GTK 4 window's spinner) asked before it went out of
sight, and waits for that word. Three ways in, each with that window and a foot terminal on one side of a card:

1. the hidden side, resized as a window opens beside the card, is turned to;
2. a parked card comes back to a tile of another size and slides in (`reveal … up`, as OmaRelay switches);
3. apps waiting out of sight are moved in and made a card in one batch (OmaRelay's rebuild).

Each is recorded frame by frame with the read-only motion probe, which reports the size each app last drew at.
A frame shows an app wrongly when the app is shown (not hidden, its workspace shown, fading in or in) while its
last picture is more than 2 px off its size. A side turned to shows none; a slide waits less than 100 ms for its
apps to draw unseen and then shows none (the 0.3.0-rc.19 core waited its full 200 ms and the GTK window came in
at its old size); a card built in view shows each app drawn at its size from its second frame (its first is what
the app last drew: nothing holds back what a batch moves in). Only the Hyprflip core and the probe are loaded.
--plugin runs the suite against another build, such as an older one; --report only prints what each way showed.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from control import environment, session_windows

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import workflow as w

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--plugin', type=Path, default=project / 'build/hyprflip.so')
parser.add_argument('--report', action='store_true', help='print what each way showed instead of checking it')
args = parser.parse_args()
root = args.session.parent
env = environment(args.session)
env.pop('notify_log', None)
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
library, probe = root / 'unseen-hyprflip.so', root / 'unseen-probe.so'
processes, checks, loaded, probed, output = [], [], None, False, None
PLACE, PARK = '50', 'special:unseen-park'
# The pilot desktop's animations.
LOOK = '''
hl.curve("snap", {type="bezier",points={{0.16,1.00},{0.30,1.00}}})
hl.curve("softOut", {type="bezier",points={{0.38,0.00},{0.20,1.00}}})
hl.curve("bfRise", {type="bezier",points={{0.22,1.00},{0.36,1.00}}})
hl.curve("mac", {type="bezier",points={{0.25,0.10},{0.25,1.00}}})
hl.animation({leaf="windowsIn",enabled=true,speed=5.5,bezier="bfRise",style="popin 92%"})
hl.animation({leaf="windowsOut",enabled=true,speed=3.5,bezier="softOut",style="popin 92%"})
hl.animation({leaf="windowsMove",enabled=true,speed=4,bezier="snap"})
hl.animation({leaf="fadeIn",enabled=true,speed=4,bezier="mac"})
hl.animation({leaf="fadeOut",enabled=true,speed=3,bezier="mac"})
hl.config({misc={background_color=0xff00ff},dwindle={force_split=2},general={gaps_in=8,gaps_out=18}})
'''


def wait(fn, seconds=8, what='condition'):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for ' + what)


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


def appear(app):
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()), what=app)
    return next(a for a, win in ipc.windows().items() if win['class'] == app)


def foot(name, color):
    app = 'hyprflip-unseen-' + name
    processes.append(subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
                                       '--override', f'colors-dark.background={color}', 'sh', '-c', 'exec cat'],
                                      env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL))
    return appear(app)


def gtk(name):
    app = 'hyprflip-unseen-' + name
    processes.append(subprocess.Popen(['python3', str(project / 'tests/gtk_fixture.py'), app, str(root / (app + '.cmd'))],
                                      env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL))
    return appear(app)


def focus(address):
    ipc.call('dispatch', f'hl.dsp.focus({{window="address:{address}"}})')
    wait(lambda: ipc.data('-j', 'activewindow').get('address') == address, what='the focus')


def move(address, workspace):
    return f'dispatch hl.dsp.window.move({{window="address:{address}",workspace="{workspace}",follow=false}})'


def cut(address): return f'dispatch hl.dsp.window.set_prop({{prop="no_anim",value="true",window="address:{address}"}})'
def card(id): return next(c for c in ipc.status()['containers'] if c['id'] == id)
def card_of(address): return next(c for c in ipc.status()['containers'] if any(address in face for face in c['faces']))
def now(): return {win['address']: win for win in json.loads(ipc.call('hf-motion-probe', 'now'))['windows']}
def off(win): return any(abs(d - g) > 2 for d, g in zip(win['drawn'], win['goal'][2:]))


def batch(*commands):
    result = subprocess.run(['hyprctl', '--batch', ' ; '.join(commands)], env=env, capture_output=True, text=True,
                            timeout=8)
    assert not result.returncode and 'error' not in result.stdout, (commands, result.stdout)


def drawn(*addresses, seconds=4):
    """Waits until each app has drawn at its size, the way a person would leave it before the next step."""
    wait(lambda: not any(off(now()[a]) for a in addresses), seconds, 'the apps to draw at their size')


def record(commands, seconds=2.5):
    ipc.call('hf-motion-probe', 'start windows')
    batch(*commands)
    time.sleep(seconds)
    frames = [f for f in json.loads(ipc.call('hf-motion-probe', 'stop')) if f['monitor'] == output]
    assert frames, 'No frames were rendered'
    return frames


def shown_wrongly(frames, addresses):
    """For each app: (ms of its first frame in view, the ms of the frames that showed its old picture)."""
    result = {}
    for address in addresses:
        seen, wrong = None, []
        for f in frames:
            win = next((x for x in f['windows'] if x['address'] == address), None)
            if not win or win['hidden'] or not win['shown'] or win['fade'] <= 0: continue
            seen = f['ms'] if seen is None else seen
            if off(win): wrong.append(round(f['ms']))
        result[address] = (seen, wrong)
    return result


def report(label, frames, addresses, names):
    result = shown_wrongly(frames, addresses)
    after = now()
    for address in addresses:
        seen, wrong = result[address]
        print(f'  {label}: {names[address]} in view from {round(seen) if seen is not None else None} ms, '
              f'{len(wrong)} frame(s) at its old size {wrong[:3]}{"…" if len(wrong) > 3 else ""} '
              f'(last {wrong[-1] if wrong else None} ms); drawn at size {not off(after[address])} after '
              f'{after[address]["drawn"]} vs {after[address]["goal"][2:]}', flush=True)
    return result


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    session_windows(env)
    shutil.copy2(args.plugin, library)
    shutil.copy2(project / 'build/motion_probe.so', probe)
    ipc.call('plugin', 'load', str(library)); loaded = library
    ipc.call('plugin', 'load', str(probe)); probed = True
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    config.write_text(original + LOOK + f'hl.monitor({{output="{output}",mode="1920x1080@60",position="2000x0",scale=1}})\n'
                      f'hl.workspace_rule({{workspace="{PLACE}",monitor="{output}"}})\n'
                      'hl.config({plugin={hyprflip={notifications=false,card_frame=false}}})\n')
    ipc.call('reload'); assert not ipc.call('configerrors'), ipc.call('configerrors')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', f'hl.dsp.focus({{workspace={PLACE}}})')
    assert ipc.status()['reveal_slide'] is True

    tile = foot('tile', '203040')
    a = foot('a', 'c04040')
    g = gtk('g')
    (root / 'hyprflip-unseen-g.cmd').write_text('spin')
    b = foot('b', '40a040')
    names = {a: 'foot a', g: 'GTK g', b: 'foot b'}
    x, y = ipc.windows()[a]['at']; width, height = ipc.windows()[a]['size']
    reply = ipc.batch([f'hyprflip restore quiet tiled 1 0 {x} {y} {width} {height} front horizontal {a} {a}:1 '
                       f'back vertical {g} {g}:1 {b}:1'])[-1]
    assert reply.startswith('ok'), reply
    wait(lambda: len(ipc.status()['containers']) == 1, what='the card')
    id = card_of(g)['id']
    wait(lambda: not ipc.status()['animating'], what='the card to settle')
    drawn(a, g, b)

    # 1. The hidden side is resized: a window opens beside the card while its front shows
    assert ipc.action(f'card {id} show front').startswith('ok')
    wait(lambda: card(id)['active'] == 0 and not ipc.status()['animating'], what='the front')
    before = {k: ipc.windows()[k]['size'] for k in (g, b)}
    focus(a)
    extra = foot('extra', '806040')
    wait(lambda: all(ipc.windows()[k]['size'] != before[k] for k in (g, b)), what='the hidden side to be resized')
    time.sleep(.5)
    print('1. the hidden side, resized, is turned to', flush=True)
    frames = record([f'hyprflip card {id} show back'])
    first = report('turn', frames, (g, b), names)
    drawn(g, b)

    # 2. Parked, then brought back to a tile of another size, sliding in as OmaRelay switches cards
    members = [m for face in card(id)['faces'] for m in face]
    batch(*[cut(m) for m in members], f'hyprflip card {id} workspace {PARK} silent')
    wait(lambda: card(id)['workspace']['name'] == PARK, what='the card parked')
    ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{extra}"}})')
    wait(lambda: extra not in ipc.windows(), what='the extra window to close')
    time.sleep(.5)
    print('2. a parked card comes back to a bigger tile and slides in', flush=True)
    frames = record([*[cut(m) for m in members], f'hyprflip card {id} workspace {PLACE} silent',
                     f'hyprflip card {id} reveal 0.7 up'])
    wait_ms = ipc.status()['last_slide_wait_ms']
    print(f'  the slide waited {wait_ms} ms', flush=True)
    second = report('slide', frames, (g, b), names)
    drawn(g, b)

    # 3. Out of sight, then moved in and made a card in one batch, as OmaRelay builds a card again
    assert ipc.action(f'card {id} ungroup').startswith('ok')
    wait(lambda: not ipc.status()['containers'], what='the card to come apart')
    batch(*[cut(m) for m in (a, g, b)], *[move(m, PARK) for m in (a, g, b)])
    wait(lambda: all(ipc.windows()[m]['workspace']['name'] == PARK for m in (a, g, b)), what='the apps parked')
    time.sleep(.5)
    focus(tile)
    print('3. apps out of sight are moved in and made a card in one batch', flush=True)
    x, y = ipc.windows()[tile]['at']
    frames = record([*[move(m, PLACE) for m in (a, g, b)],
                     f'hyprflip restore quiet tiled 1 0 {x} {y} 800 800 front horizontal {a} {a}:1 '
                     f'back vertical {g} {g}:1 {b}:1'])
    third = report('build', frames, (g, b), names)

    if not args.report:
        wrong = {names[k]: v[1] for k, v in first.items() if v[1]}
        assert not wrong, wrong
        passed('a side resized while hidden is turned to with its apps drawn at their new size')
        wrong = {names[k]: v[1] for k, v in second.items() if v[1]}
        assert wait_ms is not None and wait_ms < 100 and not wrong, (wait_ms, wrong)
        passed(f'a card back at another size slides in after {round(wait_ms)} ms, its apps drawn at their new size')
        late = {names[k]: v[1] for k, v in third.items() if v[1] and (len(v[1]) > 1 or v[1][0] > round(v[0]))}
        assert not late, late
        passed('a card built in view has each app drawn at its size from its second frame')
finally:
    for process in processes:
        process.terminate()
    for process in processes:
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill()
    if probed: ipc.call('plugin', 'unload', str(probe))
    if loaded: ipc.call('plugin', 'unload', str(loaded))
    config.write_text(original)
    ipc.call('reload')
    if output: ipc.call('output', 'remove', output)
    print(json.dumps({'passed': checks}), flush=True)
