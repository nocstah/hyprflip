#!/usr/bin/env python3
"""A window that opens while a card has the keyboard stays outside it, and the card draws on once it closes.

Found on the pilot desktop (2026-11-17): a chat link in a card's browser made another app open a window, which
looked as if it shared the browser's face; once it closed, the browser showed a picture of its top half until it
was restarted. With Hyprland's group:auto_group, a window that opens joins the focused window's group unless that
group is locked, and a card is one locked native group: the window is tiled beside the card (dwindle splits the
card's tile, as it splits any focused window), and with the classic appearance nothing outlines the card, so the
two look like one face. Checked here, with the pilot desktop's settings (auto_group and focus_on_activate on, the
classic appearance, a 12 px card gap, scale 1.5, its animations):

1. a window opening while the card's front app has the keyboard is its own tile, outside the card's faces and
   native group, and the card's group stays locked, also after OmaRelay's show, hold, park, unpark and reveal and a
   configuration reload;
2. once that window closes, the front app is drawn at the size it gets back;
3. a pane that leaves a face (attached, then closed) leaves the face's other app drawn at its size again.

The front app is the GTK 4 fixture drawing every frame, or with --browser a Chromium-family browser (a throwaway
profile under the session) on a page that draws every frame. The motion probe reports the size each app last
drew at. Only the Hyprflip core and the probe are loaded; --plugin runs the suite against another build.
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
parser.add_argument('--browser', type=Path, help='a Chromium-family browser for the front app, such as chromium')
args = parser.parse_args()
root = args.session.parent
env = environment(args.session)
env.pop('notify_log', None)
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
library, probe, profile = root / 'outside-hyprflip.so', root / 'outside-probe.so', root / 'outside-browser'
processes, checks, loaded, probed, output = [], [], None, False, None
PLACE, PARK = '50', 'special:outside-park'
# The pilot desktop's animations and settings.
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
hl.config({misc={background_color=0xff00ff,focus_on_activate=true},dwindle={force_split=2},
           general={gaps_in=8,gaps_out=18},group={auto_group=true}})
hl.config({plugin={hyprflip={notifications=false,card_frame=false,card_gap=12}}})
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


def appear(app, seconds=8, title=None):
    def match(win): return win['class'] == app if title is None else win['title'].startswith(title)
    wait(lambda: any(match(win) for win in ipc.windows().values()), seconds, app)
    return next(a for a, win in ipc.windows().items() if match(win))


def foot(name, color):
    app = 'hyprflip-outside-' + name
    processes.append(subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
                                       '--override', f'colors-dark.background={color}', 'sh', '-c', 'exec cat'],
                                      env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL))
    return appear(app)


def gtk(name, command=''):
    app = 'hyprflip-outside-' + name
    (root / (app + '.cmd')).write_text(command)
    processes.append(subprocess.Popen(['python3', str(project / 'tests/gtk_fixture.py'), app, str(root / (app + '.cmd'))],
                                      env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL))
    return appear(app)


def close_gtk(name, address):
    (root / ('hyprflip-outside-' + name + '.cmd')).write_text('close')
    wait(lambda: address not in ipc.windows(), what=name + ' to close')


def browser():
    shutil.rmtree(profile, ignore_errors=True)
    profile.mkdir()
    page = profile / 'page.html'
    # draws every frame, as the GTK window's spinner does
    page.write_text('<title>hyprflip-outside-page</title><body style="margin:0;background:#234;color:#fff">'
                    '<div id=count></div><script>let n=0;(function f(){document.getElementById("count").textContent='
                    '(++n)+" "+innerWidth+"x"+innerHeight;requestAnimationFrame(f)})()</script></body>')
    homes = {key: str(profile / name) for key, name in
             (('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache'), ('XDG_DATA_HOME', 'data'))}
    for home in homes.values(): Path(home).mkdir()
    processes.append(subprocess.Popen(
        [str(args.browser), f'--user-data-dir={profile / "profile"}', '--no-first-run', '--no-default-browser-check',
         '--disable-background-networking', '--disable-component-update', '--disable-sync', '--ozone-platform=wayland',
         '--class=hyprflip-outside-browser', page.as_uri()],
        env=env | homes, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    return appear('hyprflip-outside-browser', 30, 'hyprflip-outside-page')


def focus(address):
    ipc.call('dispatch', f'hl.dsp.focus({{window="address:{address}"}})')
    wait(lambda: ipc.data('-j', 'activewindow').get('address') == address, what='the focus')


def locked(address):
    """Whether the window's native group is locked, read through an error since eval only answers ok."""
    expression = (f'(function() local w = hl.get_window("address:{address}") '
                  'return w and w.group and tostring(w.group.locked) or "no group" end)()')
    result = subprocess.run(['hyprctl', 'eval', f'error("VALUE=" .. {expression}, 0)'], env=env, capture_output=True,
                            text=True, timeout=8)
    assert 'VALUE=' in result.stdout, result.stdout
    return result.stdout.split('VALUE=', 1)[1].strip()


def card(id):
    found = next((c for c in ipc.status()['containers'] if c['id'] == id), None)
    assert found, f'card {id} came apart: {ipc.status()["containers"]}'
    return found


def now(): return {win['address']: win for win in json.loads(ipc.call('hf-motion-probe', 'now'))['windows']}
def off(win): return any(abs(d - g) > 2 for d, g in zip(win['drawn'], win['goal'][2:]))
def overlap(a, b): return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def drawn(*addresses, seconds=2):
    wait(lambda: not any(off(now()[a]) for a in addresses), seconds, 'the apps to draw at their size')


def outside(id, front, name):
    """A window opens while the card's front app has the keyboard: it stays outside the card, which stays locked."""
    faces = card(id)['faces']
    focus(front)
    extra = gtk(name)
    wait(lambda: not ipc.status()['animating'] and ipc.windows()[front]['size'] != [0, 0], what='the layout')
    time.sleep(.4)
    win, members = ipc.windows()[extra], [m for face in faces for m in face]
    box = lambda a: [*ipc.windows()[a]['at'], *ipc.windows()[a]['size']]
    assert not win['grouped'], win['grouped']
    assert card(id)['faces'] == faces, (faces, card(id)['faces'])
    assert sorted(ipc.windows()[front]['grouped']) == sorted(members), ipc.windows()[front]['grouped']
    assert locked(front) == 'true', locked(front)
    assert not overlap(box(extra), box(front)), (box(extra), box(front))
    return extra


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
    config.write_text(original + LOOK + f'hl.monitor({{output="{output}",mode="2400x1600@60",position="2000x0",scale=1.5}})\n'
                      f'hl.workspace_rule({{workspace="{PLACE}",monitor="{output}"}})\n')
    ipc.call('reload'); assert not ipc.call('configerrors'), ipc.call('configerrors')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', f'hl.dsp.focus({{workspace={PLACE}}})')

    foot('tile', '203040')
    front = browser() if args.browser else gtk('front', 'spin')
    back = foot('back', '40a040')
    time.sleep(1)
    x, y = ipc.windows()[front]['at']; width, height = ipc.windows()[front]['size']
    reply = ipc.batch([f'hyprflip restore quiet tiled 0 0 {x} {y} {width} {height} front horizontal {front} {front}:1 '
                       f'back horizontal {back} {back}:1'])[-1]
    assert reply.startswith('ok'), reply
    wait(lambda: len(ipc.status()['containers']) == 1, what='the card')
    id = ipc.status()['containers'][0]['id']
    wait(lambda: not ipc.status()['animating'], what='the card to settle')
    assert ipc.status()['containers'][0]['native_group'] is True
    drawn(front, seconds=4)
    full = ipc.windows()[front]['size']

    # 1. A window opens beside the focused card, again after what OmaRelay and the user do to a card
    extra = outside(id, front, 'extra')
    close_gtk('extra', extra)
    drawn(front)
    steps = {
        'show back, show front': [f'hyprflip card {id} show back', f'hyprflip card {id} show front'],
        'hold, park, unpark, reveal up': [f'hyprflip card {id} hold', f'hyprflip card {id} workspace {PARK} silent',
                                          f'hyprflip card {id} workspace {PLACE} silent',
                                          f'hyprflip card {id} reveal 0.7 up'],
        'a configuration reload': ['reload'],
    }
    for label, commands in steps.items():
        for command in commands:
            reply = ipc.batch([command])[-1]
            assert reply.startswith('ok'), (command, reply)
            time.sleep(.3)
        wait(lambda: not ipc.status()['animating'] and card(id)['workspace']['name'] == PLACE, what=label)
        drawn(front, seconds=4)
        extra = outside(id, front, 'extra')
        close_gtk('extra', extra)
        drawn(front)
    passed('a window that opens while a card has the keyboard tiles beside it, outside its locked native group, '
           'also after show, hold, park, unpark, reveal and a reload')

    # 2. The window beside the card closes: the front app draws at the size it gets back
    extra = outside(id, front, 'extra')
    split = ipc.windows()[front]['size']
    assert split[1] < full[1], (split, full)
    drawn(front)
    close_gtk('extra', extra)
    wait(lambda: ipc.windows()[front]['size'] == full, what='the card to get its tile back')
    drawn(front)
    time.sleep(1)
    assert not off(now()[front]), now()[front]
    passed(f'once the window beside the card closes, its front app is drawn at {full} again (it was {split})')

    # 3. A pane leaves the front face: the face's other app draws at its size again
    pane = gtk('pane')
    focus(pane); assert ipc.batch(['hyprflip mark'])[-1].startswith('ok')
    focus(front); reply = ipc.batch(['hyprflip attach vertical'])[-1]
    assert reply.startswith('ok'), reply
    wait(lambda: pane in card(id)['faces'][0] and not ipc.status()['animating'], what='the pane in the front face')
    drawn(front, pane, seconds=4)
    shared = ipc.windows()[front]['size']
    close_gtk('pane', pane)
    wait(lambda: card(id)['faces'][0] == [front], what='the pane to leave the face')
    wait(lambda: ipc.windows()[front]['size'] == full, what='the front app to fill the face')
    drawn(front)
    time.sleep(1)
    assert not off(now()[front]), now()[front]
    passed(f'a pane that leaves a face leaves its other app drawn at {full} (it was {shared})')
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
    shutil.rmtree(profile, ignore_errors=True)
    print(json.dumps({'passed': checks}), flush=True)
