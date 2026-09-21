#!/usr/bin/env python3
"""Exercise face layout edits and rollback in a disposable compositor."""
import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from control import environment

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('session', type=Path)
args = p.parse_args()
root, project = args.session.parent, Path(__file__).resolve().parent.parent
env = environment(args.session)
spec = importlib.util.spec_from_file_location('hf_layout_setup', project / 'scripts/setup.py')
setup = importlib.util.module_from_spec(spec); sys.modules[spec.name] = setup; spec.loader.exec_module(setup)
ipc = setup.Hyprctl(env)
config = root / 'hyprland.lua'; original = config.read_text()
loaded, processes, checks = [], [], []
output, completed = None, False


class Menu:
    def __init__(self, *answers): self.answers = iter(answers)
    def choose(self, prompt, choices):
        answer = next(self.answers)
        assert answer in [c.value for c in choices], (prompt, choices, answer)
        return answer


def wait(predicate):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.04)
    raise AssertionError('State did not settle: ' + json.dumps(ipc.status()))
def passed(message): checks.append(message); print('PASS', message, flush=True)
def active(): return ipc.data('-j', 'activewindow').get('address')
def card(): return ipc.status()['containers'][0]
def shape(): return setup.Saved.capture(card(), ipc.windows())
def edit(anchor, *answers):
    ipc.focus(anchor)
    flow = setup.Edit(ipc, Menu(*answers)); flow.apply(flow.prepare(anchor))
def spawn(name, minimum=None):
    name = 'hyprflip-layout-' + name
    if minimum:
        control = root / (name + '.command'); control.write_text('minimum ' + ' '.join(map(str, minimum)))
        command = ['python', str(project / 'tests/gtk_fixture.py'), name, str(control)]
    else: command = ['foot', '--config', '/dev/null', '--app-id', name, '--title', name, 'sh', '-c', 'exec cat']
    process = subprocess.Popen(command, env=env | {'GDK_BACKEND': 'wayland', 'GSK_RENDERER': 'cairo'},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(process)
    wait(lambda: any(w['class'] == name for w in ipc.windows().values()))
    return next(a for a, w in ipc.windows().items() if w['class'] == name)
def attach(anchor, pane, axis='horizontal'): ipc.focused((pane, 'mark'), (anchor, 'attach ' + axis))
def visible():
    c, windows = card(), ipc.windows()
    for side, face in enumerate(c['faces']):
        for a in face: assert windows[a]['acceptsInput'] == (c['unfolded'] or side == c['active'])


try:
    assert not ipc.data('-j', 'plugin', 'list')
    for source in (project / 'build/containers/provider/upstream/libhy3.so', project / 'build/containers/core/hyprflip.so'):
        target = root / ('layout-' + source.name); shutil.copy2(source, target)
        ipc.call('plugin', 'load', str(target)); loaded.append(target)
    config.write_text(original.replace('layout="dwindle"', 'layout="hy3"'))
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('eval', 'hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})')
    names = {m['name'] for m in ipc.data('-j', 'monitors')}; ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    ipc.call('eval', f'hl.monitor({{output="{output}",mode="2560x1440@60",position="2000x0",scale=1}})')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})'); ipc.call('dispatch', 'hl.dsp.focus({workspace=40})')
    a, b, c, d = [spawn(name) for name in ('front', 'back', 'third', 'fourth')]
    ipc.focused((a, 'mark'), (b, 'pair')); attach(b, c); attach(b, d)
    assert ipc.status()['layout_controls']
    helper = setup.Setup(ipc, Menu())
    helper.restore_ratios({'windows': [b, c, d], 'axis': 'horizontal', 'ratios': [.6, .25, .15]})
    before = shape()['faces'][1]['ratios']
    edit(b, 'layout', 'layout vertical')
    after = shape()['faces'][1]
    assert after['axis'] == 'vertical' and all(abs(x-y) < .025 for x,y in zip(before, after['ratios'])), (before, after)
    assert active() == b; visible()
    edit(b, 'layout', 'layout balance')
    assert all(abs(r-1/3) < .015 for r in shape()['faces'][1]['ratios'])
    edit(b, 'layout', 'layout horizontal')
    assert shape()['faces'][1]['axis'] == 'horizontal'
    passed('Beside/Stacked retain three pane proportions and focus; Equal sizes balances the current side')

    # Transfer a pane which was not focused in the menu, then follow it.
    edit(b, 'other_side', d)
    assert card()['faces'] == [[a, d], [b, c]] and card()['active'] == 0 and active() == d
    ipc.action('flip'); assert active() == b
    ipc.action('flip'); assert active() == d
    visible()
    passed('moving an unfocused pane follows it to the other face; subsequent flips remember both selections')

    ipc.action('unfold'); edit(d, 'layout', 'layout vertical')
    edit(d, 'other_side', d)
    assert card()['faces'] == [[a], [b, c, d]] and card()['unfolded'] and active() == d
    visible()
    ipc.focus(a)
    try: ipc.action('other_side')
    except setup.SetupError as error: assert 'at least two' in str(error)
    else: raise AssertionError('Cannot leave an empty face')
    ipc.action('unfold')
    e = spawn('fifth'); attach(a, e)
    ipc.focus(a); before = deepcopy(card())
    try: ipc.action('other_side')
    except setup.SetupError as error: assert 'three apps' in str(error)
    else: raise AssertionError('Cannot overfill the other face')
    assert card() == before
    passed('unfolded edits preserve both visible faces; empty sides and a fourth pane are refused without mutation')

    # A narrow surviving pane must not get a negative weight when another moves.
    ipc.focus(b)
    helper.restore_ratios({'windows': [b, c, d], 'axis': 'horizontal', 'ratios': [.8, .1, .1]})
    edit(b, 'other_side', c)
    assert card()['faces'] == [[a, e, c], [b, d]]
    ratios = shape()['faces'][1]['ratios']
    assert abs(ratios[0] - 8/9) < .025 and all(r > 0 for r in ratios), ratios
    passed('transfers keep unequal remaining panes proportional and positive')

    ipc.action('unpair')
    for address in (a,b,c,d,e): ipc.move(address, 41)
    x, y, z = spawn('min-front'), spawn('min-back'), spawn('wide', [1500, 100])
    ipc.focused((x, 'mark'), (y, 'pair')); attach(y, z, 'vertical')
    ipc.focus(y); before, saved = deepcopy(card()), shape()
    for answers in (('layout', 'layout horizontal'), ('other_side', z)):
        try: edit(y, *answers)
        except setup.SetupError: pass
        else: raise AssertionError('Minimum width should reject this change')
        assert card() == before and active() == y, (card(), before)
        assert shape() == saved, (shape(), saved)
        visible()
    passed('minimum-size failures restore exact membership, order, axis, proportions, focus and folded state')
    ipc.action('flip'); ipc.action('flip'); visible()
    # Recreate so the destination is a leaf, not a one-child wrapper left by
    # the preceding refused transfer. Its outer weight differs when unfolded.
    ipc.action('unpair'); ipc.focused((x, 'mark'), (y, 'pair')); attach(y, z, 'vertical')
    ipc.action('unfold'); ipc.focus(x)
    ipc.call('dispatch', 'hl.dsp.window.resize({x=0,y=150,relative=true})')
    ipc.focus(y)
    before = deepcopy(card())
    boxes = {a:(ipc.windows()[a]['at'],ipc.windows()[a]['size']) for a in (x,y,z)}
    try: edit(y, 'other_side', z)
    except setup.SetupError: pass
    else: raise AssertionError('Wide app must not move into a horizontal split')
    assert card() == before and active() == y
    restored_boxes = {a:(ipc.windows()[a]['at'],ipc.windows()[a]['size']) for a in (x,y,z)}
    assert restored_boxes == boxes, (restored_boxes, boxes)
    passed('failed transfer also preserves unequal outer face sizes while unfolded')
    # Exit with a populated card so teardown also traverses the edited tree.
    completed = True
finally:
    config.write_text(original); ipc.call('reload')
    for target in reversed(loaded): ipc.call('plugin', 'unload', str(target))
    for process in processes:
        if process.poll() is None: process.terminate(); process.wait(timeout=5)
    if output: ipc.call('output', 'remove', output)
    (root / 'layout-results.json').write_text(json.dumps({'completed': completed, 'checks': checks}, indent=2))
