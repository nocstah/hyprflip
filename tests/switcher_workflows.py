#!/usr/bin/env python3
"""The face switcher and the face slide, in a disposable compositor with only the core loaded.

Cards with three or more faces slide sideways along their faces instead of flipping. Holding
the flip key shows a strip of face previews; the same switcher is driven here
through hyprctl hyprflip switcher open|step|pick|cancel|last, since simulated
keys do not reach bindings in a nested session.
"""
import sys, time, shutil, subprocess
from pathlib import Path
project = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(project / 'tests'), str(project / 'scripts')]
from control import environment
from PIL import Image, ImageStat
import workflow as w
session = Path(sys.argv[1]); root = session.parent; out = root
env = environment(session) | {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
ipc = w.Hyprctl(env); procs = []
def wait(fn, what, t=8):
    d = time.monotonic() + t
    while time.monotonic() < d:
        if fn(): return
        time.sleep(.03)
    x = ipc.status()
    raise AssertionError('timed out: ' + what + ' ' + str(x.get('switcher')) + ' pending=' + str(x.get('switch_pending')) + ' active=' + str(x['containers'][0]['active']))
def ok(m): print('PASS', m, flush=True)
colours = {'a': 'c0392b', 'b': '27ae60', 'c': '2980b9', 'd': '8e44ad', 'e': 'd35400', 'f': '16a085'}
def spawn(n):
    app = 'sw-' + n
    procs.append(subprocess.Popen(['foot', '--config', '/dev/null', '-o', f'colors-dark.background={colours[n]}', '-o', 'font=monospace:size=28',
        '--app-id', app, '--title', app, 'sh', '-c', f'echo FACE {n.upper()}; cat'], env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(x['class'] == app for x in ipc.windows().values()), app)
    return next(a for a, x in ipc.windows().items() if x['class'] == app)
def st(): return ipc.status()
def card(): return st()['containers'][0]
def shot(name, output): subprocess.run(['grim', '-l', '1', '-o', output, str(out / name)], env=env, check=True, timeout=8)
def previews(image, s, card_box, monitor):
    """The mean colour of the middle of each preview, in face order."""
    x, y, width, _ = s['panel']; n = s['faces']; pad = 14
    w_ = (width - pad * (n + 1)) / n; h_ = w_ * card_box[3] / card_box[2]
    found = []
    for i in range(n):
        left = x - monitor['x'] + pad + i * (w_ + pad); top = y - monitor['y'] + pad
        box = tuple(round(v) for v in (left + w_ * .25, top + h_ * .3, left + w_ * .75, top + h_ * .75))
        found.append(tuple(round(c) for c in ImageStat.Stat(image.crop(box)).mean))
    return found
config = root / 'hyprland.lua'; original = config.read_text()
try:
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    src = project / 'build/hyprflip.so'; tgt = root / 'sw.so'; shutil.copy2(src, tgt); ipc.call('plugin', 'load', str(tgt))
    config.write_text(original + f'\nhl.monitor({{output="{output}",mode="1920x1080@60",position="4000x0",scale=1}})\n'
                      'hl.workspace_rule({workspace="52",monitor="' + output + '"})\n')
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})'); ipc.call('dispatch', 'hl.dsp.focus({workspace=52})')
    m = next(m for m in ipc.data('-j', 'monitors') if m['name'] == output)
    apps = [spawn(n) for n in 'abcd']
    line = ' '.join(f'{wd} horizontal {a} {a}:1' for wd, a in zip(['front', 'back', 'face', 'face'], apps))
    r = ipc.batch([f'hyprflip restore quiet floating 0 0 {m["x"]+360} {m["y"]+190} 1200 700 ' + line])[-1]; assert r.startswith('ok'), r
    ipc.call('dispatch', f'hl.dsp.focus({{window="address:{apps[0]}"}})')
    wait(lambda: card()['active'] == 0, 'front')
    time.sleep(.3)

    assert ipc.action('switcher open').startswith('ok')
    s = st()['switcher']; assert s['open'] and s['faces'] == 4 and s['previews'] == 4 and s['selected'] == 1, s
    time.sleep(.2); shot('open.png', output)
    ipc.action('switcher step'); assert st()['switcher']['selected'] == 2
    ipc.action('switcher step back'); ipc.action('switcher step'); ipc.action('switcher step')
    assert st()['switcher']['selected'] == 3
    time.sleep(.2); shot('step.png', output)
    assert ipc.action('switcher pick 4').startswith('ok')
    wait(lambda: card()['active'] == 3, 'pick 4'); assert not st()['switcher']['open']
    ok('IPC switcher opens with four previews, steps and picks face 4')

    assert ipc.action('switcher last').startswith('ok'); wait(lambda: card()['active'] == 0, 'last face')
    assert ipc.action('switcher last').startswith('ok'); wait(lambda: card()['active'] == 3, 'last face again')
    ok('going to the last face toggles between the two latest faces')
    assert ipc.action('switcher open').startswith('ok'); assert st()['switcher']['selected'] == 0
    ipc.action('switcher cancel'); assert not st()['switcher']['open'] and card()['active'] == 3
    ipc.action('switcher open'); ipc.call('dispatch', 'hl.dsp.focus({workspace=53})')
    wait(lambda: not st()['switcher']['open'], 'workspace change closes'); ipc.call('dispatch', 'hl.dsp.focus({workspace=52})')
    ok('cancel and leaving the workspace put the switcher away without turning')
    ipc.call('eval', 'hl.config({animations={enabled=true},plugin={hyprflip={duration_ms=1600}}})')
    assert st()['transition'] == 'flip'
    assert ipc.action('switcher open').startswith('ok'); assert ipc.action('switcher pick 2').startswith('ok')
    wait(lambda: 0 < st()['progress'] < 1, 'the turn to start')
    assert st()['last_fallback'] == '', st()['last_fallback']
    wait(lambda: card()['active'] == 1 and st()['progress'] in (0, 1), 'animated pick')
    ok('a pick turns the card, animated, with no fallback')

    # Swipes, fed through hyprctl: the card is 1200 wide and shows face 2.
    ipc.call('eval', 'hl.config({plugin={hyprflip={duration_ms=420}}})')
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={m["x"]+900},y={m["y"]+500}}})')
    def swipe(*moves, end='end'):
        assert ipc.action('swipe begin 3').startswith('ok')
        for dx, ms in moves: assert ipc.action(f'swipe move {dx} {ms}').startswith('ok')
        assert ipc.action('swipe ' + end).startswith('ok')
        wait(lambda: not st()['swiping'] and st()['progress'] in (0, 1), 'swipe to settle')
        time.sleep(.6)
        return card()['active']
    try:
        ipc.action('swipe begin 2'); raise AssertionError('two fingers were taken')
    except w.SetupError: pass
    assert ipc.action('swipe begin 3').startswith('ok'); ipc.action('swipe move -300 400')
    time.sleep(.2); assert st()['swiping'] and card()['active'] == 1, st()
    shot('drag.png', output); ipc.action('swipe end'); time.sleep(.8)
    assert card()['active'] == 1, card()
    ok('a short slow swipe follows the fingers and settles back on the same face')
    assert swipe(*[(-120, 40)] * 6) == 2
    ok('a swipe left past halfway settles on the next face')
    assert swipe((-60, 10), (-60, 10)) == 3
    ok('a quick flick carries on to the next face')
    assert swipe(*[(120, 40)] * 16) == 2
    ok('a long swipe right resists past one face and settles on the face before')
    before = card()['active']; assert swipe(*[(-120, 40)] * 6, end='cancel') == before
    ok('a cancelled swipe returns to its face')

    # Jumping straight to a face, and face names.
    ipc.call('eval', 'hl.config({plugin={hyprflip={duration_ms=0}}})')
    assert ipc.action('face 3').startswith('ok'); wait(lambda: card()['active'] == 2, 'face 3')
    ipc.call('eval', 'hl.plugin.hyprflip.face(1)'); wait(lambda: card()['active'] == 0, 'Lua face(1)')
    try:
        ipc.action('face 7'); raise AssertionError('face 7 was accepted')
    except w.SetupError as error:
        assert 'from 1 to 6' in str(error), error
    ok('face <n> and the Lua face(n) go straight to a face, and refuse one out of range')

    tricky = 'Mail & Chat 50%'
    assert ipc.action('name ' + tricky).startswith('ok')
    assert ipc.action(f"card {card()['id']} name 3 Code").startswith('ok')
    assert card()['names'] == [tricky, '', 'Code', ''], card()['names']
    import card_restore
    line = card_restore.describe(card())
    assert ipc.action(f"card {card()['id']} ungroup").startswith('ok'); wait(lambda: not st()['containers'], 'ungroup')
    assert ipc.batch(['hyprflip restore quiet ' + line])[-1].startswith('ok'), line
    assert card()['names'] == [tricky, '', 'Code', ''], card()['names']
    assert ipc.action(f"card {card()['id']} name 3").startswith('ok') and card()['names'][2] == ''
    try:
        ipc.action('name ' + 'x' * 60); raise AssertionError('a long name was accepted')
    except w.SetupError: pass
    ok('faces take names, keep them through the description updates restore from, and clear them')

    # Six faces: the switcher's tiles still fit the screen, and picking the sixth turns to it.
    # Apps fade in for ten seconds, so faces 5 and 6 are still fading in when the switcher opens, and the apps on
    # hidden faces are unfocused, at inactive_opacity and dimmed.
    ipc.call('eval', 'hl.animation({leaf="fadeIn",enabled=true,speed=100,bezier="linear"}) '
                     'hl.config({decoration={inactive_opacity=0.6,dim_inactive=true,dim_strength=0.5}})')
    e, f = spawn('e'), spawn('f')
    ipc.focused((e, 'mark'), (apps[0], 'attach face')); wait(lambda: len(card()['faces']) == 5, 'face 5')
    ipc.focused((f, 'mark'), (e, 'attach face')); wait(lambda: len(card()['faces']) == 6, 'face 6')
    assert card()['faces'][4:] == [[e], [f]] and card()['active'] == 5, card()
    assert ipc.action('face 1').startswith('ok'); wait(lambda: card()['active'] == 0, 'face 1')
    assert ipc.action('switcher open').startswith('ok')
    # It opens on the face shown last, the sixth; a step moves off it before `switcher pick 6` picks it.
    # That is the IPC pick. The switcher's digit keys read evdev KEY_1 to KEY_9, and wtype numbers its keys in a
    # keymap of its own, so no suite presses them.
    s = st()['switcher']; assert s['open'] and s['faces'] == 6 and s['previews'] == 6 and s['selected'] == 5, s
    ipc.action('switcher step'); assert st()['switcher']['selected'] == 0, st()['switcher']
    x, y, width, height = s['panel']
    assert m['x'] <= x and x + width <= m['x'] + m['width'] and m['y'] <= y and y + height <= m['y'] + m['height'], (s, m)
    time.sleep(.2); shot('six.png', output)
    seen = previews(Image.open(out / 'six.png').convert('RGB'), s, card()['box'], m)
    wanted = [tuple(int(colours[n][i:i + 2], 16) for i in (0, 2, 4)) for n in 'abcdef']
    assert all(abs(a - b) <= 12 for got, want in zip(seen, wanted) for a, b in zip(got, want)), (seen, wanted)
    assert ipc.action('switcher pick 6').startswith('ok')
    wait(lambda: card()['active'] == 5, 'pick 6'); assert not st()['switcher']['open']
    try:
        ipc.action(f"card {card()['id']} show 7"); raise AssertionError('show 7 was accepted')
    except w.SetupError as error:
        assert 'from 1 to 6' in str(error), error
    ok('a six-face switcher opens with six previews inside the screen, and switcher pick 6 turns to the sixth face')
    ok('each preview shows its face as it looks when turned to, with apps still fading in, unfocused or dimmed')

    # A fullscreen or maximized card: before each snapshot the switcher moves fullscreen to that face's app, which
    # Hyprland brings to its focused opacity only on a later frame.
    for mode in ('fullscreen', 'maximized'):
        ipc.call('dispatch', f'hl.dsp.window.fullscreen({{mode="{mode}"}})'); wait(lambda: card()['fullscreen'], mode)
        time.sleep(.3)
        assert ipc.action('switcher open').startswith('ok')
        s = st()['switcher']; assert s['open'] and s['previews'] == 6, s
        time.sleep(.2); shot(mode + '.png', output)
        ipc.action('switcher cancel'); assert not st()['switcher']['open']
        seen = previews(Image.open(out / (mode + '.png')).convert('RGB'), s, card()['box'], m)
        assert all(abs(a - b) <= 12 for got, want in zip(seen, wanted) for a, b in zip(got, want)), (mode, seen, wanted)
        ipc.call('dispatch', f'hl.dsp.window.fullscreen({{mode="{mode}"}})'); wait(lambda: not card()['fullscreen'], mode + ' off')
    ok('a fullscreen or maximized card shows every face at its focused look in the switcher')
finally:
    for p in procs: p.terminate()
