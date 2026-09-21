#!/usr/bin/env python3
"""Check multi-pane transitions, reversals and cleanup on a disposable 4K output."""
import argparse
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import time
from control import environment

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
parser.add_argument('--captures', action='store_true')
args = parser.parse_args()
env = environment(args.session)
root = args.session.parent
project = Path(__file__).resolve().parent.parent
config = root / 'hyprland.lua'; original = config.read_text()
loaded, processes, checks, metrics = [], [], [], {}
output = None
completed = False


def ctl(*args):
    p = subprocess.run(['hyprctl', *map(str,args)], env=env, capture_output=True, text=True, timeout=10)
    reply = p.stdout.strip()
    if p.returncode or reply.startswith('error') or 'Lua error' in reply or 'could not be loaded' in reply:
        raise AssertionError((args,reply,p.stderr))
    return reply
def data(*args): return json.loads(ctl(*args))
def state(): return data('hyprflip','status')
def card(): return state()['containers'][0]
def action(value): return ctl('hyprflip',value)
def lua(value): return ctl('repl',value)
def windows(): return {w['address']: w for w in data('-j','clients')}
def focus(address): ctl('dispatch',f'hl.dsp.focus({{window="address:{address}"}})')
def wait(predicate):
    deadline = time.monotonic()+8
    while time.monotonic()<deadline:
        if predicate(): return
        time.sleep(.012)
    raise AssertionError('Did not settle: '+json.dumps(state()))
def passed(message): checks.append(message); print('PASS',message,flush=True)
def setting(mode,duration=420): lua(f'hl.config({{plugin={{hyprflip={{transition="{mode}",duration_ms={duration},notifications=false}}}}}})')
def spawn(name,color):
    app='hyprflip-transition-'+name
    process=subprocess.Popen(['foot','--config','/dev/null','--app-id',app,'--title',name,
        '--override',f'colors-dark.background={color}','--override','colors-dark.foreground=fafafa',
        '--override','font=monospace:size=20','sh','-c',
        'printf "\\n  %s\\n\\n  One card. Two sides.\\n\\n  LEFT       CENTRE       RIGHT\\n" "$1"; exec cat',
        'hyprflip',name.upper()],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    processes.append(process)
    wait(lambda:any(w['class']==app for w in windows().values()))
    return next(a for a,w in windows().items() if w['class']==app)
def visible():
    current,clients=card(),windows()
    for side,face in enumerate(current['faces']):
        for a in face: assert clients[a]['acceptsInput']==(side==current['active']), (a,current)
def capture(name):
    subprocess.run(['grim','-l','1','-o',output,str(root/(name+'.png'))],env=env,capture_output=True,check=True,timeout=8)


try:
    assert not data('-j','plugin','list')
    for source in (project/'build/containers/provider/upstream/libhy3.so',project/'build/containers/core/hyprflip.so',project/'build/motion_probe.so'):
        target=root/('transitions-'+source.name);shutil.copy2(source,target)
        ctl('plugin','load',target);loaded.append(target)
    config.write_text(original.replace('layout="dwindle"','layout="hy3"'))
    ctl('reload');assert not ctl('configerrors')
    names={m['name'] for m in data('-j','monitors')};ctl('output','create','headless')
    output=next(m['name'] for m in data('-j','monitors') if m['name'] not in names)
    lua(f'hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5}})')
    ctl('dispatch',f'hl.dsp.focus({{monitor="{output}"}})');ctl('dispatch','hl.dsp.focus({workspace=30})')
    setting('flip',0)
    a,b=spawn('front','244961'),spawn('back','674455')
    focus(a);action('mark');focus(b);action('pair')
    extras=[]
    for name,color in (('front-2','345a62'),('front-3','28484d'),('back-2','694b3b'),('back-3','5b3e54')):
        address=spawn(name,color);extras.append(address)
        focus(address);action('mark');focus(a if name.startswith('front') else b);action('attach horizontal')
    assert list(map(len,card()['faces']))==[3,3]
    modes=state()['transition_modes']
    for rotation in (0,1):
        lua(f'hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5,transform={rotation}}})')
        # Stack vertically on portrait outputs, giving every pane enough room.
        if rotation:
            setting('instant',0)
            for i,address in enumerate(extras):
                focus(address);action('release')
                ctl('dispatch',f'hl.dsp.window.move({{window="address:{address}",workspace="31",follow=false}})')
            for i,address in enumerate(extras):
                ctl('dispatch',f'hl.dsp.window.move({{window="address:{address}",workspace="30",follow=false}})')
                focus(address);action('mark');focus(a if i<2 else b);action('attach vertical')
        focus(a);time.sleep(.6)
        for mode in modes:
            setting(mode);focus(a);time.sleep(.1)
            if mode=='instant':
                action('flip');assert not state()['animating'] and card()['active']==1;visible()
                continue
            runs=[]
            for _ in range(2):
                ctl('hf-motion-probe','start');action('flip')
                assert state()['animating'],state()
                wait(lambda:not state()['animating'])
                frames=[f for f in data('hf-motion-probe','stop') if f['monitor']==output and f['state']['animating']]
                assert len(frames)>=8,(mode,len(frames),state())
                assert not state()['last_fallback'],state()
                assert all(f['next_frame_pending'] for f in frames)
                runs.append(frames);visible()
            steady=runs[1]
            gaps=[r['ms']-l['ms'] for l,r in zip(steady,steady[1:])]
            costs=sorted(f['cpu_render_ms'] for f in steady)
            key=f'{rotation}-{mode}'
            metrics[key]={'frame_gap_median_ms':statistics.median(gaps),'frame_gap_max_ms':max(gaps),
                          'cpu_render_p95_ms':costs[round((len(costs)-1)*.95)],'capture_ms':state()['capture_ms']}
            print(key,json.dumps(metrics[key]),flush=True)
            for progress in (.25,.7):
                focus(a);action('flip');wait(lambda:state()['progress']>=progress)
                action('flip');wait(lambda:not state()['animating'])
                assert card()['active']==0;visible()
            focus(a);action('preview '+mode);wait(lambda:not state()['animating'])
            assert card()['active']==0 and state()['transition']==mode;visible()
            if args.captures:
                setting(mode,1600)
                for label,progress in (('out',.28),('in',.65)):
                    focus(a);action('flip');wait(lambda:state()['progress']>=progress)
                    capture(key+'-'+label);action('finish')
            passed(f'{key}: three panes per face render, reverse and preview with exclusive input')
    setting('portal')
    focus(a);lua('hl.config({animations={enabled=false}})');action('flip')
    assert not state()['animating'] and card()['active']==1
    lua('hl.config({animations={enabled=true}})');focus(a);time.sleep(.3)
    action('flip');ctl('reload');assert not state()['animating'];assert not ctl('configerrors')
    passed('disabled global animations switch immediately; reload settles an active transition')
    setting('dissolve',1600);focus(a);time.sleep(.3);action('flip')
    processes[-1].terminate();processes[-1].wait(timeout=5)
    wait(lambda:not state()['animating']);assert len(card()['faces'][1])==2
    passed('closing a pane during a snapshot transition restores the remaining live card')
    setting('fade',1600);focus(a);time.sleep(.3);action('flip')
    core=next(p for p in loaded if p.name=='transitions-hyprflip.so')
    ctl('plugin','unload',core);loaded.remove(core)
    assert all(not w['hidden'] for w in windows().values() if w['class'].startswith('hyprflip-transition-'))
    assert not ctl('configerrors')
    passed('unloading during a transition releases effects and leaves every surviving app usable')
    completed=True
finally:
    for process in processes:
        if process.poll() is None:process.terminate();process.wait(timeout=5)
    try:
        config.write_text(original);ctl('reload')
        for target in reversed(loaded):ctl('plugin','unload',target)
        if output:ctl('output','remove',output)
    finally:
        (root/'transition-results.json').write_text(json.dumps({'completed':completed,'checks':checks,'metrics':metrics},indent=2))
