#!/usr/bin/env python3
"""Check experimental upgrades and rollback in a disposable compositor."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
from control import environment

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('session', type=Path)
p.add_argument('--baseline-core', type=Path, required=True)
p.add_argument('--baseline-provider', type=Path, required=True)
p.add_argument('--hyprglass', type=Path, required=True)
args = p.parse_args()
env = environment(args.session)
project = Path(__file__).resolve().parent.parent
root = args.session.parent
installed = root / 'installed'
state_dir = root / f'updates-{time.time_ns()}'
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = [], []
completed = False


def ctl(*a):
    r = subprocess.run(['hyprctl', *a], env=env, text=True, capture_output=True, timeout=8)
    s = r.stdout.strip()
    if r.returncode or s.startswith('error') or 'Lua error' in s: raise AssertionError((a,s,r.stderr))
    return s


def status(): return json.loads(ctl('hyprflip','status'))
def clients(): return {w['address']:w for w in json.loads(ctl('-j','clients'))}
def focus(w): ctl('dispatch', f'hl.dsp.focus({{window="address:{w}"}})')
def action(s): return ctl('hyprflip',s)
def wait(fn):
    deadline=time.monotonic()+6
    while time.monotonic()<deadline:
        if fn(): return
        time.sleep(.04)
    raise AssertionError('State did not settle')


def spawn(name):
    name='hyprflip-upgrade-'+name
    proc=subprocess.Popen(['foot','--config','/dev/null','--app-id',name,'sh','-c','exec cat'],
                          env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    processes.append(proc)
    wait(lambda:any(w['class']==name for w in clients().values()))
    return next(w['address'] for w in clients().values() if w['class']==name)


def digest():
    return [hashlib.sha256(f.read_bytes()).hexdigest() for f in (installed/'hyprflip.so',installed/'containers/libhy3.so')]


def cards():
    return sorted((tuple(tuple(face) for face in c['faces']),c['current'],bool(c.get('unfolded'))) for c in status()['containers'])


def update(script=project/'scripts/update-containers.py', dry=False, fail=False, drift=False):
    command=['python',str(script),'--library-root',str(installed),'--state-dir',str(state_dir)]
    if dry: command.append('--dry-run')
    update_env = env
    if drift:
        # Focus another card member immediately before a mutation reaches the
        # compositor. This deterministically exercises the gap between separate
        # focus/poll and mark/attach requests, without racing the test runner.
        wrapper = root / 'focus-drift' / 'hyprctl'
        wrapper.parent.mkdir(exist_ok=True)
        wrapper.write_text('''#!/usr/bin/env python3
import json, os, subprocess, sys
from pathlib import Path
real = os.environ['HYPRFLIP_REAL_CTL']
args = sys.argv[1:]
action = (args[:1] == ['hyprflip'] and len(args) > 1 and
          args[1].split()[0] in ('mark', 'pair', 'attach', 'unfold'))
action |= args[:1] == ['eval'] and any('hl.plugin.hyprflip.' + name + '(' in ' '.join(args[1:])
                                      for name in ('mark', 'pair', 'attach', 'unfold'))
if action:
    state = json.loads(subprocess.check_output([real, 'hyprflip', 'status'], text=True))
    if state['containers']:
        target = state['containers'][0]['current']
        subprocess.run([real, 'dispatch', 'hl.dsp.focus({window="address:' + target + '"})'],
                       check=True, capture_output=True)
        with Path(os.environ['HYPRFLIP_DRIFT_LOG']).open('a') as log:
            log.write(json.dumps({'target': target, 'action': args}) + '\\n')
os.execv(real, [real, *args])
''')
        wrapper.chmod(0o755)
        update_env = env | {'PATH': str(wrapper.parent) + ':' + env['PATH'],
                            'HYPRFLIP_REAL_CTL': shutil.which('hyprctl'),
                            'HYPRFLIP_DRIFT_LOG': str(root / 'focus-drift.jsonl')}
    r=subprocess.run(command,env=update_env,capture_output=True,text=True,timeout=50)
    assert (r.returncode != 0) == fail, (r.returncode,r.stdout,r.stderr)
    return r.stdout + r.stderr


def passed(name): checks.append(name); print('PASS',name,flush=True)


try:
    assert not json.loads(ctl('-j','plugin','list'))
    (installed/'containers').mkdir(parents=True,exist_ok=True)
    for src,dst in ((args.baseline_core,installed/'hyprflip.so'),
                    (args.baseline_provider,installed/'containers/libhy3.so'),
                    (args.hyprglass,root/'upgrade-glass.so')): shutil.copy2(src,dst)
    configured=original+'\n'+''.join(f'hl.plugin.load({json.dumps(str(f))})\n' for f in
        (installed/'hyprflip.so',installed/'containers/libhy3.so',root/'upgrade-glass.so'))+'''
if hl.plugin.hy3 then hl.config({general={layout="hy3"}}) end
hl.workspace_rule({workspace="9",layout="dwindle"})
if hl.plugin.hyprflip then hl.config({plugin={hyprflip={duration_ms=0,notifications=false}}}) end
'''
    config.write_text(configured); ctl('reload'); assert not ctl('configerrors')
    wait(lambda:status()['container_provider'])
    ctl('dispatch','hl.dsp.focus({workspace=1})')
    a=next(w['address'] for w in clients().values() if w['class']=='hyprflip-front')
    b=next(w['address'] for w in clients().values() if w['class']=='hyprflip-back')
    for w in (a,b): ctl('dispatch',f'hl.dsp.window.move({{window="address:{w}",workspace="1",follow=false}})')
    c=spawn('companion')
    focus(a); action('mark'); focus(b); action('pair')
    focus(c); action('mark'); focus(b); action('attach vertical')
    focus(b); ctl('dispatch','hl.dsp.window.resize({x=0,y=90,relative=true})'); time.sleep(.4)
    focus(c)
    ctl('dispatch','hl.dsp.focus({workspace=2})')
    d,e=spawn('second-front'),spawn('second-back')
    focus(d); action('mark'); focus(e); action('pair')
    ctl('dispatch','hl.dsp.focus({workspace=9})')
    f,g=spawn('native-front'),spawn('native-back')
    focus(f); action('mark'); focus(g); action('pair')
    focus(c)
    before_cards,before_native,before_hashes=cards(),status()['pairs'],digest()
    before_ratio=clients()[b]['size'][1]/(clients()[b]['size'][1]+clients()[c]['size'][1])
    before_ws={w:clients()[w]['workspace'] for w in (a,b,c,d,e,f,g)}
    update(dry=True)
    assert digest()==before_hashes and cards()==before_cards and not state_dir.exists()
    passed('experimental dry run preserves libraries, cards and configuration')

    cover=spawn('fullscreen-cover')
    ctl('dispatch','hl.dsp.window.float({action="float"})')
    ctl('dispatch','hl.dsp.window.fullscreen({action="set",layout_aware=false})')
    assert clients()[cover]['fullscreen']
    for dry in (True,False):
        output=update(dry=dry,fail=True)
        assert 'covering a card workspace' in output,output
        assert digest()==before_hashes and cards()==before_cards and not state_dir.exists()
        assert json.loads(ctl('-j','activewindow'))['address']==cover
    ctl('dispatch','hl.dsp.window.fullscreen({action="unset",layout_aware=false})')
    ctl('dispatch',f'hl.dsp.window.close({{window="address:{cover}"}})')
    wait(lambda:cover not in clients())
    focus(c)
    passed('a fullscreen covering window blocks the update before replacing libraries or changing focus')

    update(drift=True)
    assert cards()==before_cards
    assert [(x['front'],x['back'],x['current']) for x in status()['pairs']]==[(x['front'],x['back'],x['current']) for x in before_native]
    assert all(clients()[w]['workspace']==ws for w,ws in before_ws.items())
    assert json.loads(ctl('-j','activewindow'))['address']==c
    assert digest()==[hashlib.sha256(path.read_bytes()).hexdigest() for path in
        (project/'build/containers/core/hyprflip.so',project/'build/containers/provider/upstream/libhy3.so')]
    after_ratio=clients()[b]['size'][1]/(clients()[b]['size'][1]+clients()[c]['size'][1])
    assert abs(after_ratio-before_ratio)<.025,(before_ratio,after_ratio)
    action('unfold'); assert next(x for x in status()['containers'] if a in x['faces'][0])['unfolded']
    passed('old provider upgrades with multiple cards, split proportion, native pair, app workspaces and focus preserved')
    assert (root / 'focus-drift.jsonl').read_text().splitlines()
    passed('focus changes between IPC commands cannot redirect card restoration to another app')

    # The updated provider must also survive future updates with six-pane cards.
    action('unfold')
    for anchor, name in ((a, 'front-second'), (a, 'front-third'), (b, 'back-third')):
        focus(anchor)
        extra = spawn(name)
        focus(extra); action('mark'); focus(anchor); action('attach vertical')
    six = next(x for x in status()['containers'] if a in x['faces'][0])
    assert list(map(len, six['faces'])) == [3, 3]
    focus(a); ctl('dispatch','hl.dsp.window.resize({x=0,y=35,relative=true})')
    focus(b); ctl('dispatch','hl.dsp.window.resize({x=0,y=-25,relative=true})')
    time.sleep(.4)
    before_sizes = clients()
    before_ratios = [[before_sizes[w]['size'][1] / sum(before_sizes[v]['size'][1] for v in face)
                     for w in face] for face in six['faces']]
    before_cards = cards()
    update()
    assert cards() == before_cards
    after_sizes = clients()
    for face, ratios in zip(six['faces'], before_ratios):
        actual = [after_sizes[w]['size'][1] / sum(after_sizes[v]['size'][1] for v in face) for w in face]
        assert max(abs(a-b) for a,b in zip(ratios, actual)) < .025, (ratios, actual)
    focus(b); action('unfold')
    passed('six-pane cards retain both split proportions, membership and focus across a subsequent update')

    # Exercise a load failure after both old libraries have been unloaded.
    broken=root/'broken-build'
    (broken/'scripts').mkdir(parents=True,exist_ok=True)
    (broken/'build/containers/provider/upstream').mkdir(parents=True,exist_ok=True)
    (broken/'build/containers/core').mkdir(parents=True,exist_ok=True)
    shutil.copy2(project/'scripts/update-containers.py',broken/'scripts/update-containers.py')
    (broken/'build/containers/core/hyprflip.so').write_bytes(b'not a shared object\n')
    shutil.copy2(project/'build/containers/provider/upstream/libhy3.so',broken/'build/containers/provider/upstream/libhy3.so')
    before_cards,before_hashes=cards(),digest()
    output=update(broken/'scripts/update-containers.py',fail=True)
    assert 'restoring the previous libraries and cards' in output
    assert 'Recovery needs attention' not in output,output
    assert cards()==before_cards and digest()==before_hashes
    assert len(status()['pairs'])==1 and not ctl('configerrors')
    passed('failed plugin load rolls back both libraries and restores folded/unfolded cards')
    completed=True
finally:
    try:
        # The updater loads libraries through IPC; removing their config lines
        # alone does not unload them. Keep Hyprglass loaded until both are gone.
        loaded = {item['name'] for item in json.loads(ctl('-j','plugin','list'))}
        for name, library in (('hyprflip', installed/'hyprflip.so'),
                              ('hy3', installed/'containers/libhy3.so')):
            if name in loaded:
                assert ctl('plugin','unload',str(library)) == 'ok'
        config.write_text(original+f'\nhl.plugin.load({json.dumps(str(root/"upgrade-glass.so"))})\n')
        ctl('reload'); assert not ctl('configerrors')
        config.write_text(original); ctl('reload'); assert not ctl('configerrors')
        assert not json.loads(ctl('-j','plugin','list'))
    finally:
        for proc in processes:
            if proc.poll() is None: proc.terminate()
        for proc in processes:
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=3)
        output=project/'test-results/container-upgrade.json'
        output.write_text(json.dumps({'completed':completed,'checks_passed':checks,'count':len(checks)},indent=2)+'\n')
print(f'{len(checks)} container upgrade checks passed',flush=True)
