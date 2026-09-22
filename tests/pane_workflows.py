#!/usr/bin/env python3
"""Reorder and replace real panes in an isolated compositor, with optional Chill/Glass."""
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
p.add_argument('session', type=Path); p.add_argument('--engine', type=Path); p.add_argument('--hyprglass', type=Path)
args = p.parse_args()
root, project = args.session.parent, Path(__file__).resolve().parent.parent
env = environment(args.session) | {'XDG_STATE_HOME': str(root / 'pane-state')}
spec = importlib.util.spec_from_file_location('hf_pane_setup', project / 'scripts/workflow.py')
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
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.04)
    raise AssertionError('State did not settle: ' + json.dumps(ipc.status()))
def passed(message): checks.append(message); print('PASS', message, flush=True)
def active(): return ipc.data('-j','activewindow').get('address')
def card(): return ipc.status()['containers'][0]
def boxes(addresses):
    live = ipc.windows(); return {a: (live[a]['at'],live[a]['size']) for a in addresses}
def close(address):
    ipc.call('dispatch', f'hl.dsp.window.close({{window="address:{address}"}})'); wait(lambda: address not in ipc.windows())
def edit(anchor, *answers):
    ipc.focus(anchor); flow = setup.Edit(ipc, Menu(*answers)); flow.apply(flow.prepare(anchor))
def arrange(face, axis, ratios):
    ipc.focused((face[0], 'arrange ' + axis + ''.join(f' {a}:{r}' for a,r in zip(face,ratios))))
def visible():
    c, live = card(), ipc.windows()
    for side, members in enumerate(c['faces']):
        for a in members: assert live[a]['acceptsInput'] == (c['unfolded'] or side == c['active'])
def spawn(name, minimum=None):
    name = 'hyprflip-pane-' + name
    if minimum:
        control = root / (name + '.command'); control.write_text('minimum ' + ' '.join(map(str, minimum)))
        command = ['python', str(project / 'tests/gtk_fixture.py'), name, str(control)]
    else: command = ['foot','--config','/dev/null','--app-id',name,'--title',name,'/usr/bin/cat']
    processes.append(subprocess.Popen(command, env=env | {'GDK_BACKEND':'wayland','GSK_RENDERER':'cairo'},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(w['class'] == name for w in ipc.windows().values()))
    return next(a for a,w in ipc.windows().items() if w['class'] == name)


try:
    assert not ipc.data('-j','plugin','list')
    for source in (project / 'build/containers/provider/upstream/libhy3.so', project / 'build/containers/core/hyprflip.so'):
        target = root / ('pane-' + source.name); shutil.copy2(source,target)
        ipc.call('plugin','load',str(target)); loaded.append(target)
    if args.hyprglass:
        target = root / 'pane-hyprglass.so'; shutil.copy2(args.hyprglass,target)
        ipc.call('plugin','load',str(target)); loaded.append(target)
    config.write_text(original.replace('layout="dwindle"','layout="hy3"'))
    ipc.call('reload'); assert not ipc.call('configerrors')
    ipc.call('eval','hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})')
    if args.hyprglass: ipc.call('eval','hl.plugin.hyprglass.config({enabled=true,manage_window_blur=true})')
    monitors = {m['name'] for m in ipc.data('-j','monitors')}; ipc.call('output','create','headless')
    output = next(m['name'] for m in ipc.data('-j','monitors') if m['name'] not in monitors)
    ipc.call('eval',f'hl.monitor({{output="{output}",mode="2560x1440@60",position="2000x0",scale=1}})')
    ipc.call('dispatch',f'hl.dsp.focus({{monitor="{output}"}})'); ipc.call('dispatch','hl.dsp.focus({workspace=60})')
    ipc.action('reserve 60 pane-fixture 120')
    if args.engine:
        home = root / 'pane-home'; (home / '.local/state').mkdir(parents=True,exist_ok=True)
        engine = root / 'pane-chillmode.lua'; engine.write_text(args.engine.read_text().replace('os.getenv("HOME")',json.dumps(str(home))))
        ipc.call('eval','CHILLMODE_OPTS={auto=true,auto_max=3,notify=false,keybind="",key_hide="",key_restore="",hide=false}; '
                 + f'dofile({json.dumps(str(engine))})')
    a,b,c,d = [spawn(n) for n in ('front','back','third','fourth')]
    ipc.focused((a,'mark'),(b,'pair'))
    for extra in (c,d): ipc.focused((extra,'mark'),(b,'attach horizontal'))
    arrange([b,c,d], 'horizontal', [.5,.3,.2]); ipc.focus(b)
    before = deepcopy(card()); identity = before['id']
    ipc.call('dispatch','hl.dsp.layout("togglesplit")')
    assert card()['layouts'][1]['axis'] == 'vertical'
    ipc.call('dispatch','hl.dsp.layout("togglesplit")')
    assert card() == before
    passed('the existing Super+J dispatcher still toggles beside/stacked and preserves pane order and proportions')

    for axis, move in (('horizontal','2:1'),('vertical','1:2')):
        edit(b,'layout','layout ' + axis)
        before = deepcopy(card()); edit(b,'layout','reorder',move)
        expected = before['faces'][1][:]; i,j = map(int,move.split(':')); expected[i],expected[j] = expected[j],expected[i]
        assert card()['faces'][1] == expected and card()['id'] == identity and active() == b
        assert card()['layouts'] == before['layouts']; visible()
    passed('three-pane reordering follows the current direction, keeps slot sizes and retains original focus')

    x = spawn('replacement'); ipc.focus(b)
    before, positions = deepcopy(card()), boxes([a,b,c,d,x])
    target = before['faces'][1][1]
    edit(b,'replace',target,x)
    expected = deepcopy(before['faces']); expected[1][1] = x
    assert card()['faces'] == expected and card()['id'] == identity and active() == b
    assert card()['layouts'] == before['layouts'] and card()['box'] == before['box']
    assert boxes([x])[x] == positions[target] and boxes([target])[target] == positions[x]
    assert target in ipc.windows(); visible()
    passed('an unfocused pane on a full side is replaced atomically, keeping its slot, card and focus; the old app stays open')

    # The outgoing original front may close after replacement; it must no longer own this card.
    ipc.focus(a); before = deepcopy(card()); edit(a,'replace',target)
    assert card()['faces'][0] == [target] and card()['id'] == identity and active() == target
    assert card()['box'] == before['box']; close(a)
    assert card()['id'] == identity and card()['faces'][0] == [target]; visible()
    front = target
    passed('the sole front app can be replaced, and subsequently closing the released original leaves the card intact')

    y = spawn('unfolded-replacement'); ipc.focus(b); ipc.action('unfold')
    ipc.focus(front); ipc.call('dispatch','hl.dsp.window.resize({x=100,y=0,relative=true})')
    ipc.focus(b); before = deepcopy(card()); positions = boxes([front,*before['faces'][1],y])
    edit(b,'replace',b,y)
    assert card()['unfolded'] and card()['current'] == y and active() == y
    assert card()['box'] == before['box'] and card()['layouts'][0] == before['layouts'][0]
    assert boxes([y])[y] == positions[b]
    close(b); assert card()['id'] == identity; visible()
    passed('focused replacement keeps unequal unfolded face geometry and follows the new app; closing the old back is safe')

    tall = spawn('minimum', [100,600]); ipc.focus(y)
    before = deepcopy(card()); positions = boxes([front,*before['faces'][1],tall])
    try: edit(y,'replace',x,tall)
    except setup.SetupError: pass
    else: raise AssertionError('The replacement must fit the existing pane height')
    assert card() == before and boxes(positions) == positions and active() == y; visible()
    passed('a replacement that cannot fit is refused with exact card and outside-window geometry restored')

    # Explicit addresses cannot target the opposite face, another member or a vanished app.
    for command in (f'replace {front} {tall}', f'replace {x} {y}', f'replace {x} 0x1', f'replace {x} {tall} extra'):
        try: ipc.action(command)
        except setup.SetupError: pass
        else: raise AssertionError('Invalid replacement request was accepted')
        assert card() == before
    passed('invalid targets, grouped replacements and malformed requests never change the card')

    ipc.move(tall,62)
    ipc.call('dispatch','hl.dsp.focus({workspace=61})'); remote = spawn('remote')
    if args.engine:
        wait(lambda: ipc.windows()[remote]['floating'] and 'chillmode' in ipc.windows()[remote].get('tags',[]))
    else: ipc.call('dispatch',f'hl.dsp.window.float({{window="address:{remote}",action="enable"}})')
    ipc.focus(y); before = deepcopy(card()); outgoing = before['faces'][1][-1]
    edit(y,'replace',outgoing,'workspace:61',remote)
    assert card()['faces'][1][-1] == remote and card()['id'] == identity and active() == y
    assert card()['unfolded'] == before['unfolded'] and card()['layouts'] == before['layouts']
    assert not ipc.windows()[remote]['floating'] and ipc.windows()[remote]['workspace']['id'] == 60
    assert outgoing in ipc.windows() and ipc.windows()[outgoing]['workspace']['id'] == 60; visible()
    passed('remote floating/Chill apps can replace a pane; the previous app remains open on the card workspace')

    ipc.move(outgoing,63)
    ipc.call('dispatch','hl.dsp.focus({workspace=62})'); ipc.focus(tall)
    if args.engine: wait(lambda: ipc.windows()[tall]['floating'])
    else: ipc.call('dispatch',f'hl.dsp.window.float({{window="address:{tall}",action="enable"}})')
    original_float = deepcopy(ipc.windows()[tall]); ipc.focus(y); before = deepcopy(card())
    try: edit(y,'replace',x,'workspace:62',tall)
    except setup.SetupError: pass
    else: raise AssertionError('A remote minimum-size failure should roll back import and tiling')
    assert card() == before and active() == y
    restored = ipc.windows()[tall]
    for key in ('pid','class','workspace','floating','at','size','tags'):
        assert restored.get(key) == original_float.get(key), (key,restored.get(key),original_float.get(key))
    passed('a refused remote replacement restores its original workspace, floating geometry and Chill tags')

    ipc.focused((remote,'release')); ipc.focus(y)
    before = deepcopy(card()); edit(y,'layout','reorder')
    assert card()['faces'][1] == list(reversed(before['faces'][1]))
    assert card()['layouts'] == before['layouts'] and card()['unfolded'] and active() == y
    ipc.action('unfold'); ipc.action('flip'); ipc.action('flip'); visible()
    passed('two-pane Swap app positions needs one layout choice; folding and flipping remain usable afterward')

    # A replacement may come from an ordinary hy3 split. The released app must
    # fit that vacated slot too, and the surrounding group must remain intact.
    ipc.action('unpair')
    for address,w in ipc.windows().items():
        if w['class'].startswith('hyprflip-pane-'): ipc.move(address,61)
    ipc.call('dispatch','hl.dsp.focus({workspace=60})')
    ipc.action('reserve 60 pane-fixture 120')
    large = spawn('large-outgoing', [100,900]); back = spawn('new-back')
    ipc.focused((large,'mark'),(back,'pair'))
    source = spawn('nested-source')
    ipc.call('dispatch','hl.plugin.hy3.make_group("v")')
    siblings = [spawn('nested-' + n) for n in ('second','third')]
    assert ipc.windows()[source]['size'][1] < 900
    ipc.focus(large); before = deepcopy(card()); positions = boxes([large,back,source,*siblings])
    try: edit(large,'replace',source)
    except setup.SetupError: pass
    else: raise AssertionError('The released app must fit the replacement app’s old slot')
    assert card() == before and boxes(positions) == positions and active() == large
    passed('replacement refuses an outside slot smaller than the released app minimum, restoring both groups exactly')

    ipc.focus(back); before = deepcopy(card()); positions = boxes(positions)
    edit(back,'replace',source)
    assert card()['faces'] == [[large],[source]] and card()['id'] == before['id'] and active() == source
    assert boxes([source])[source] == positions[back] and boxes([back])[back] == positions[source]
    assert boxes(siblings) == {a:positions[a] for a in siblings}
    stable = deepcopy(card()); positions = boxes([large,source,back,*siblings])
    ipc.focus(siblings[0]); ipc.call('dispatch','hl.dsp.layout("togglesplit")')
    outside = [ipc.windows()[a] for a in [back,*siblings]]
    assert len({w['at'][1] for w in outside}) == 1 and len({w['at'][0] for w in outside}) == 3
    assert card() == stable
    ipc.call('dispatch','hl.dsp.layout("togglesplit")')
    assert boxes(positions) == positions; visible()
    passed('replacing from an ordinary hy3 split preserves its siblings, proportions and independent layout controls')
    completed = True
finally:
    if args.engine: ipc.call('eval','if chillmode then chillmode.unload() end')
    for name in ('pane-hyprflip.so','pane-libhy3.so','pane-hyprglass.so'):
        target = root / name
        if target in loaded: ipc.call('plugin','unload',str(target))
    config.write_text(original); ipc.call('reload')
    for process in processes:
        if process.poll() is None: process.terminate(); process.wait(timeout=5)
    if output: ipc.call('output','remove',output)
    (root / 'pane-results.json').write_text(json.dumps({'completed':completed,'checks':checks},indent=2))
