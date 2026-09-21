#!/usr/bin/env python3
"""Record card motion and verify interruption on a disposable GPU-rendered output.

Timings measure CPU render submission and render intervals, not GPU execution or
physical scanout. Captures and unfold sampling are separate from measured turns.
"""
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
parser.add_argument('--plugin', type=Path, default=Path('build/hyprflip.so'))
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--duration', type=int, default=420)
parser.add_argument('--captures', action='store_true')
parser.add_argument('--max-panes', type=int, choices=(2, 3), default=2)
parser.add_argument('--both-faces', action='store_true', help='Populate both faces for a worst-case pane-count comparison')
parser.add_argument('--require-redraw', action='store_true', help='Assert the fixed core requests every next turn frame')
args = parser.parse_args()
env = environment(args.session)
root = args.session.parent
config = root / 'hyprland.lua'
original = config.read_text()
args.output.mkdir(parents=True, exist_ok=True)
processes, loaded, results, checks = [], [], {}, []
output = None
completed = False


def ctl(*arguments):
    result = subprocess.run(['hyprctl', *map(str, arguments)], env=env,
                            capture_output=True, text=True, timeout=8)
    reply = result.stdout.strip()
    if result.returncode or reply.startswith('error') or 'Lua error' in reply or 'could not be loaded' in reply:
        raise AssertionError((arguments, reply, result.stderr))
    return reply


def lua(code): return ctl('repl', code)
def state(): return json.loads(ctl('hyprflip', 'status'))
def card(): return state()['containers'][0]
def clients(): return {w['address']: w for w in json.loads(ctl('-j', 'clients'))}
def active(): return json.loads(ctl('-j', 'activewindow')).get('address')
def action(command): return ctl('hyprflip', command)
def wait(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.012)
    raise AssertionError('Animation or layout did not settle: ' + json.dumps(state()))
def focus(address):
    ctl('dispatch', f'hl.dsp.focus({{window="address:{address}"}})')
    wait(lambda: active() == address)
def duration(value): lua(f'hl.config({{plugin={{hyprflip={{duration_ms={value},notifications=false}}}}}})')
def passed(message): checks.append(message); print('PASS', message, flush=True)
def percentile(values, fraction): return sorted(values)[round((len(values) - 1) * fraction)]


def spawn(name, color):
    app = 'hyprflip-motion-' + name
    command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
               '--override', f'colors-dark.background={color}',
               '--override', 'colors-dark.foreground=243645',
               '--override', 'font=monospace:size=20', 'sh', '-c',
               'printf "\\n  %s\\n\\n  One card. Two sides.\\n\\n  LEFT       CENTRE       RIGHT\\n" "$1"; exec cat',
               'hyprflip-motion', name.upper()]
    processes.append(subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(w['class'] == app for w in clients().values()))
    return next(w['address'] for w in clients().values() if w['class'] == app)


def visible():
    current, windows = card(), clients()
    for side, face in enumerate(current['faces']):
        for address in face:
            assert windows[address]['acceptsInput'] == (current['unfolded'] or side == current['active'])


def record(reverse_at=None, reverse_twice=False):
    ctl('hf-motion-probe', 'start')
    action('flip')
    assert state()['animating'], state()
    if reverse_at is not None:
        wait(lambda: state()['progress'] >= reverse_at)
        action('flip')
        if reverse_twice:
            time.sleep(.025)
            action('flip')
    wait(lambda: not state()['animating'])
    raw = json.loads(ctl('hf-motion-probe', 'stop'))
    frames = [f for f in raw if f['monitor'] == output]
    assert frames, (output, 'Recorded outputs:', sorted({f['monitor'] for f in raw}), 'Frames:', len(raw))
    assert not state()['last_fallback'], state()
    visible()
    return frames


def capture(name):
    before = state()
    subprocess.run(['grim', '-l', '1', '-o', output, str(args.output / (name + '.png'))], env=env,
                   check=True, timeout=6, capture_output=True)
    return {'before': before, 'after': state()}


try:
    assert not json.loads(ctl('-j', 'plugin', 'list')), 'Use a fixture without loaded plugins'
    for source, name in ((Path('build/containers/provider/upstream/libhy3.so'), 'motion-hy3.so'),
                         (args.plugin, 'motion-core.so'), (Path('build/motion_probe.so'), 'motion-probe.so')):
        target = root / name
        shutil.copy2(source, target)
        ctl('plugin', 'load', target); loaded.append(target)
    config.write_text(original.replace('layout="dwindle"', 'layout="hy3"'))
    ctl('reload'); assert not ctl('configerrors')
    names = {m['name'] for m in json.loads(ctl('-j', 'monitors'))}
    ctl('output', 'create', 'headless')
    output = next(m['name'] for m in json.loads(ctl('-j', 'monitors')) if m['name'] not in names)
    lua(f'hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5}})')
    ctl('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ctl('dispatch', 'hl.dsp.focus({workspace=30})')
    a, b = spawn('front', 'e7edf2'), spawn('back', 'cfdfec')
    extras = [[spawn(f'{side}-companion-{i}', 'cfdfec') for i in range(1, args.max_panes)]
              for side in ('front', 'back')]
    for app in sum(extras, []):
        ctl('dispatch', f'hl.dsp.window.move({{window="address:{app}",workspace="31",follow=false}})')
    focus(a); action('mark'); focus(b); action('pair')
    for transform in (0, 1):
        lua(f'hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5,transform={transform}}})')
        # Use the installed Omarchy movement curve for the unfold comparison.
        lua('hl.curve("motion-test", {type="bezier",points={{0.23,1},{0.32,1}}}); '
            'hl.animation({leaf="windowsMove",enabled=true,speed=3.79,bezier="motion-test"})')
        for panes in range(1, args.max_panes + 1):
            if panes >= 2:
                for side, anchor in enumerate((a, b)):
                    if side == 0 and not args.both_faces: continue
                    app = extras[side][panes-2]
                    ctl('dispatch', f'hl.dsp.window.move({{window="address:{app}",workspace="30",follow=false}})')
                    focus(app); action('mark'); focus(anchor)
                    action('attach ' + ('horizontal' if transform == 0 else 'vertical'))
                # Uneven panes make a per-pane lighting seam easier to detect.
                focus(b)
                ctl('dispatch', 'hl.dsp.window.resize({x=100,y=60,relative=true})')
            focus(a); time.sleep(.8)
            duration(args.duration)
            key = f'rotation-{transform}-back-panes-{panes}'
            runs = [record() for _ in range(4)]
            results[key] = {'runs': runs}
            active_runs = [[f for f in run if f['state']['animating']] for run in runs]
            assert min(map(len, active_runs)) >= 8, 'Too few rendered frames to assess motion'
            gaps = [r['ms'] - l['ms'] for run in active_runs[1:] for l, r in zip(run, run[1:])]
            errors = [abs(args.duration * (r['state']['progress'] - l['state']['progress']) - (r['ms'] - l['ms']))
                      for run in active_runs for l, r in zip(run, run[1:])]
            costs = [f['cpu_render_ms'] for run in active_runs[1:] for f in run]
            pending = [f['next_frame_pending'] for run in active_runs for f in run]
            result = {'duration_ms': args.duration, 'front_panes': panes if args.both_faces else 1, 'back_panes': panes,
                      'runs': runs,
                      'frame_gap_median_ms': statistics.median(gaps),
                      'frame_gap_p95_ms': percentile(gaps, .95),
                      'cpu_render_p95_ms': percentile(costs, .95),
                      'first_turn_cpu_max_ms': max(f['cpu_render_ms'] for f in active_runs[0]),
                      'next_frame_requested_fraction': statistics.mean(pending),
                      'pose_clock_error_p95_ms': percentile(errors, .95)}
            assert result['pose_clock_error_p95_ms'] < 3, result
            if args.require_redraw:
                assert all(pending), 'An active turn did not request its next frame'
            print(key, json.dumps({k: v for k, v in result.items() if k != 'runs'}), flush=True)
            results[key] = result
            result['reversals'] = []
            for at, twice in ((.25, False), (.49, False), (.8, False), (.55, True)):
                focus(a)
                result['reversals'].append(record(at, twice))
                assert active() == (b if twice else a)
            passed(f'{key}: timed flips and reversals preserve the selected face and exclusive input')
            if args.captures:
                focus(a); duration(1600)
                images = {'rest-front': capture(key + '-rest-front')}
                result['captures'] = images
                for name, progress in (('outgoing', .29), ('edge', .43), ('incoming', .68)):
                    # Separate turns keep screencopy/PNG latency from skipping
                    # the next requested pose, especially on a 4K output.
                    focus(a); action('flip')
                    wait(lambda: state()['progress'] >= progress)
                    images[name] = capture(key + '-' + name)
                    action('finish')
                images['rest-back'] = capture(key + '-rest-back')
            focus(a); duration(args.duration)
            action('unfold')
            assert card()['unfolded']; visible()
            samples = []
            started = time.monotonic()
            while time.monotonic() - started < .65:
                windows = clients()
                samples.append({'ms': (time.monotonic() - started) * 1000,
                                'boxes': {w: [*windows[w]['at'], *windows[w]['size']] for face in card()['faces'] for w in face}})
                time.sleep(.02)
            result['unfold'] = samples
            if args.captures: capture(key + '-unfolded')
            focus(b); action('unfold')
            assert not card()['unfolded'] and active() == b
            visible()
            duration(0); action('flip')
            assert not state()['animating'] and active() == a
            visible()
        for side, anchor in enumerate((a, b)):
            if side == 0 and not args.both_faces: continue
            for app in extras[side]:
                focus(app); action('release')
                ctl('dispatch', f'hl.dsp.window.move({{window="address:{app}",workspace="31",follow=false}})')
        focus(a)
    passed('unfold/refold retain focus; disabled animation switches immediately in every arrangement')
    completed = True
finally:
    if root / 'motion-core.so' in loaded:
        action('finish')
        if state()['containers']:
            focus(card()['current']); action('unpair')
    for process in processes:
        if process.poll() is None: process.terminate()
    for process in processes:
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
    config.write_text(original)
    ctl('reload')
    for library in reversed(loaded): ctl('plugin', 'unload', library)
    if output: ctl('output', 'remove', output)
    assert not ctl('configerrors')
    (args.output / 'results.json').write_text(json.dumps(
        {'completed': completed, 'checks': checks, 'cases': results}, indent=2) + '\n')
