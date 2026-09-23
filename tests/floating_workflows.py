#!/usr/bin/env python3
"""Native floating-card lifecycle tests in an explicitly disposable compositor."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from control import environment

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import workflow as w

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('session', type=Path)
p.add_argument('--dwindle', action='store_true', help='Use only the core plugin and the native dwindle card backend')
args = p.parse_args()
root = args.session.parent
env = environment(args.session) | {'XDG_STATE_HOME': str(root / 'state'), 'XDG_DATA_HOME': str(root / 'data')}
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'; original = config.read_text()
processes, loaded, checks = [], [], []
output = None


class Menu:
    def __init__(self, *answers): self.answers = iter(answers)
    def choose(self, prompt, choices):
        answer = next(self.answers)
        assert answer in [c.value for c in choices], (prompt, answer, choices)
        return answer
    def input(self, prompt): return next(self.answers)


def wait(fn):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.04)
    raise AssertionError('Timed out')
def passed(message): checks.append(message); print('PASS', message, flush=True)
def spawn(name):
    name = 'hyprflip-floating-' + name
    process = subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', name, '--title', name, 'cat'],
                               env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(process)
    wait(lambda: any(win['class'] == name for win in ipc.windows().values()))
    return next(a for a, win in ipc.windows().items() if win['class'] == name)
def card(): return ipc.status()['containers'][0]
def visible():
    c, windows = card(), ipc.windows()
    for s, face in enumerate(c['faces']):
        for address in face:
            assert windows[address]['acceptsInput'] == (c['unfolded'] or s == c['active']), (c, windows[address])
    for face in c['faces']:
        if len(face) > 1:
            a, b = (windows[x] for x in face[:2])
            assert a['at'][0] + a['size'][0] <= b['at'][0] or a['at'][1] + a['size'][1] <= b['at'][1], (a,b)
def edit(anchor, *answers):
    ipc.focus(anchor)
    flow=w.Edit(ipc, Menu(*answers)); flow.apply(flow.prepare(anchor))
def create(a,b,c):
    ipc.focused((a,'mark'),(b,'card' if args.dwindle else 'pair'),(c,'mark'),(b,'attach horizontal'))


try:
    assert not ipc.data('-j','plugin','list'), 'Use a fresh nested session without --containers'
    names = {m['name'] for m in ipc.data('-j','monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j','monitors') if m['name'] not in names)
    libraries = [project/'build/hyprflip.so'] if args.dwindle else [
        project/'build/containers/provider/upstream/libhy3.so', project/'build/containers/core/hyprflip.so']
    for source in libraries:
        target=root/('float-'+source.name);shutil.copy2(source,target)
        ipc.call('plugin','load',str(target));loaded.append(target)
    config.write_text((original if args.dwindle else original.replace('layout="dwindle"','layout="hy3"')) +
                     f'\nhl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5}})\n' +
                     ''.join(f'hl.workspace_rule({{workspace="{n}",monitor="{output}"}})\n' for n in (41, 43)))
    ipc.call('reload');assert not ipc.call('configerrors')
    ipc.call('eval','hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0,notifications=false}}})')
    ipc.call('dispatch',f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch','hl.dsp.focus({workspace=41})')
    a,b,c,d,e = [spawn(n) for n in ('front','back','third','fourth','replacement')]
    create(a,b,c); before=deepcopy(card());ipc.action('floating')
    assert card()['floating'] and card()['faces']==before['faces'];visible()
    passed('converting a tiled multi-app card retains both faces, ratios and input visibility')

    ipc.call('dispatch','hl.dsp.window.resize({x=900,y=600})')
    for address in (b,c):
        ipc.focus(address); box=card()['box'];windows=ipc.windows()
        ipc.call('dispatch','hl.dsp.window.move({x=17,y=11,relative=true})')
        after=ipc.windows()
        for face in card()['faces']:
            for member in face: assert after[member]['at']==[windows[member]['at'][0]+17,windows[member]['at'][1]+11]
        assert card()['box'][:2]==[box[0]+17,box[1]+11]
    old_size=card()['box'][2:]
    ipc.call('dispatch','hl.dsp.window.resize({x=100,y=50,relative=true})')
    assert card()['box'][2:]==[old_size[0]+100,old_size[1]+50], (old_size,card()['box']);visible()
    passed('moving and resizing either visible pane changes the shared outer frame')

    for mode in ('flip','vertical','slide','fade','dissolve','portal'):
        ipc.call('eval',f'hl.config({{animations={{enabled=true}},plugin={{hyprflip={{duration_ms=120,transition="{mode}"}}}}}})')
        source=card()['active'];ipc.action('flip');wait(lambda:not ipc.status()['animating'])
        assert card()['active']==1-source;visible()
    ipc.action('peek');wait(lambda:not ipc.status()['animating']);ipc.action('peek end');wait(lambda:not ipc.status()['animating']);visible()
    passed('every animated transition and peek preserves floating panes')
    ipc.call('eval','hl.config({animations={enabled=false},plugin={hyprflip={duration_ms=0}}})')
    ipc.focus(b);ipc.action('unfold');assert card()['unfolded'];visible();ipc.action('unfold')
    edit(b,'layout','layout vertical');assert card()['layouts'][1]['axis']=='vertical';visible()
    edit(b,'layout','layout balance')
    ipc.focused((d,'mark'),(b,'attach vertical'));assert card()['faces'][1]==[b,c,d];visible()
    edit(b,'other_side',d);assert card()['faces']==[[a,d],[b,c]];visible()
    ipc.focus(b);ipc.action('replace '+c+' '+e);assert card()['faces']==[[a,d],[b,e]];visible()
    ipc.focus(d);ipc.action('release');assert card()['faces']==[[a],[b,e]];visible()
    passed('floating cards support unfold, layout edits, add, transfer, replace and remove')

    ipc.focus(b);ipc.action('floating');assert not card()['floating'];visible()
    ipc.action('floating');assert card()['floating'];ipc.call('reload');visible()
    ipc.call('dispatch','hl.dsp.window.fullscreen({mode="fullscreen"})')
    ipc.call('dispatch','hl.dsp.window.fullscreen({mode="fullscreen"})');visible()
    passed('tile/float, configuration reload and fullscreen round trips retain membership')

    ipc.focus(a)
    recipe=w.Saved.capture(card(),ipc.windows());recipe['workspace']=43
    store=w.RecipeStore(env);store.update('Comms',recipe,store.read().get('Comms'))
    flow=w.Saved(ipc,Menu());plan=flow.prepare_named('Comms',recipe,41,a);flow.apply(plan)
    assert ipc.data('-j','activeworkspace')['id']==43
    assert all(ipc.windows()[x]['workspace']['id']==43 for f in card()['faces'] for x in f)
    ipc.action('workspace 41');ipc.action('unpair')
    plan=flow.prepare_named('Comms',recipe,41,ipc.data('-j','activewindow').get('address'));flow.apply(plan)
    assert card()['floating'] and ipc.data('-j','activeworkspace')['id']==43;visible()
    passed('saved floating card opens and relocates an already open card to its assigned workspace')

    # Cold start must collect all apps on the assigned workspace before grouping.
    apps=root/'data/applications';apps.mkdir(parents=True,exist_ok=True)
    for address in (a,b,e):
        win=ipc.windows()[address];name=win['class']
        (apps/(name+'.desktop')).write_text('[Desktop Entry]\nType=Application\nName='+name+'\nStartupWMClass='+name+'\nExec=/usr/bin/foot --config=/dev/null --app-id='+name+' --title='+name+' /usr/bin/cat\n')
    for address in (a,b,e): ipc.call('dispatch',f'hl.dsp.window.close({{window="address:{address}"}})')
    wait(lambda:all(address not in ipc.windows() for address in (a,b,e)))
    ipc.call('dispatch','hl.dsp.focus({workspace=41})')
    flow=w.Saved(ipc,Menu());plan=flow.prepare_named('Comms',recipe,41,ipc.data('-j','activewindow').get('address'));flow.apply(plan)
    assert card()['floating'] and ipc.data('-j','activeworkspace')['id']==43;visible()
    a=card()['faces'][0][0];b,e=card()['faces'][1]
    passed('cold opening launches every app on the assigned workspace and restores floating faces')

    # Close the unfocused app, then the last app on the hidden face.
    ipc.focus(b);ipc.call('dispatch',f'hl.dsp.window.close({{window="address:{e}"}})')
    wait(lambda:e not in ipc.windows());assert card()['faces']==[[a],[b]];visible()
    ipc.call('dispatch',f'hl.dsp.window.close({{window="address:{a}"}})')
    wait(lambda:a not in ipc.windows());assert not ipc.status()['containers']
    assert ipc.windows()[b]['acceptsInput'] and not ipc.windows()[b]['grouped']
    passed('closing a pane repairs its face; closing a whole face releases remaining apps')

    ipc.call('dispatch','hl.dsp.focus({workspace=41})')
    x,y,z=[spawn(n) for n in ('unload-front','unload-back','unload-third')]
    create(x,y,z);ipc.action('floating')
    ipc.call('plugin','unload',str(loaded.pop()))
    for address in (x,y,z):
        win=ipc.windows()[address];assert win['acceptsInput'] and not win['grouped']
    ipc.call('dispatch','hl.dsp.window.move({x=20,y=20,relative=true})')
    passed('unloading restores core window targets; released apps remain movable')
finally:
    for process in processes:
        if process.poll() is None: process.terminate()
    for library in reversed(loaded):
        try: ipc.call('plugin','unload',str(library))
        except Exception: pass
    try: config.write_text(original);ipc.call('reload')
    except Exception: pass
    if output: ipc.call('output','remove',output)
    (root/'floating-results.json').write_text(json.dumps(checks,indent=2))
