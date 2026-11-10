#!/usr/bin/env python3
"""A swap with hold and reveal, as another program sends it in one hyprctl --batch: a still
picture of what leaves, and the real open animation for what arrives. Only the Hyprflip core
and the read-only motion probe are loaded. Start the session with --notify-recorder."""
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
args = parser.parse_args()
root = args.session.parent
env = environment(args.session)
if 'notify_log' not in env:
    raise SystemExit('Start the nested session with --notify-recorder')
notify_log = Path(env.pop('notify_log'))
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks = [], []
library, probe = root / 'reveal-hyprflip.so', root / 'reveal-probe.so'
loaded, probed, output, spare = None, False, None, None
PLACE, PARK = '40', 'special:reveal-park'
WALLPAPER = 255, 0, 255
# The pilot desktop's animations, whose open starts at a 92% box.
LOOK = '''
hl.curve("mac", {type="bezier",points={{0.25,0.10},{0.25,1.00}}})
hl.curve("snap", {type="bezier",points={{0.16,1.00},{0.30,1.00}}})
hl.curve("softOut", {type="bezier",points={{0.38,0.00},{0.20,1.00}}})
hl.curve("bfRise", {type="bezier",points={{0.22,1.00},{0.36,1.00}}})
hl.animation({leaf="windowsIn",enabled=true,speed=5.5,bezier="bfRise",style="popin 92%"})
hl.animation({leaf="windowsOut",enabled=true,speed=3.5,bezier="softOut",style="popin 92%"})
hl.animation({leaf="windowsMove",enabled=true,speed=4,bezier="snap"})
hl.animation({leaf="fadeIn",enabled=true,speed=4,bezier="mac"})
hl.animation({leaf="fadeOut",enabled=true,speed=3,bezier="mac"})
hl.config({misc={background_color=0xff00ff},dwindle={force_split=2}})
if hl.plugin.hyprflip then hl.config({plugin={hyprflip={duration_ms=0,notifications=true}}}) end
hl.window_rule({name="reveal-still",match={class="hyprflip-reveal-still"},no_anim=true})
hl.window_rule({name="reveal-ruled",match={class="hyprflip-reveal-ruled"},no_blur=true})
'''


def wait(fn, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.02)
    raise AssertionError(ipc.status())


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


def spawn(name, color):
    app = 'hyprflip-reveal-' + name
    command = ['foot', '--config', '/dev/null', '--app-id', app, '--title', name,
               '--override', f'colors-dark.background={color}', 'sh', '-c', 'exec cat']
    processes.append(subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    return next(a for a, win in ipc.windows().items() if win['class'] == app)


def active(): return ipc.data('-j', 'activewindow').get('address')
def box(address): return [*ipc.windows()[address]['at'], *ipc.windows()[address]['size']]
def fadeouts(): return int(ipc.call('hf-motion-probe', 'fadeouts'))
def prop(address, name): return json.loads(ipc.call('-j', 'getprop', 'address:' + address, name))[name]
def set_prop(address, name, value):
    return f'dispatch hl.dsp.window.set_prop({{prop="{name}",value="{value}",window="address:{address}"}})'
def move(address, workspace):
    return f'dispatch hl.dsp.window.move({{window="address:{address}",workspace="{workspace}",follow=false}})'
def card_of(window): return next(c for c in ipc.status()['containers'] if any(window in face for face in c['faces']))
def frame_of(id): return next(f for f in ipc.status()['card_frames'] if f['id'] == id)


def focus(address):
    ipc.call('dispatch', f'hl.dsp.focus({{window="address:{address}"}})')
    wait(lambda: active() == address)


def pointer():
    at = ipc.data('-j', 'cursorpos')
    return at['x'], at['y']


def rest(over):
    """Leaves the pointer off-centre over a tile, where a warp to any window's centre shows."""
    x, y, width, height = box(over)
    point = x + width // 4, y + height // 3
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={point[0]},y={point[1]}}})')
    assert pointer() == point, (over, point, pointer())
    return point


def batch(*commands):
    """One hyprctl --batch: no frame falls between its requests. Replies stay unread here: a hold or reveal never decides."""
    result = subprocess.run(['hyprctl', '--batch', ' ; '.join(commands)], env=env, capture_output=True, text=True, timeout=8)
    assert not result.returncode and 'error' not in result.stdout, (commands, result.stdout)


def swap(leaving, arriving, factor=None, hold=True):
    """Swaps a window for a window, in the order docs/SCRIPTING.md gives."""
    return ([set_prop(a, 'no_anim', 'true') for a in (leaving, arriving)]
            + ([f'hyprflip card {leaving} hold'] if hold else [])
            + [move(leaving, PARK), move(arriving, PLACE),
               f'hyprflip card {arriving} reveal' + (f' {factor}' if factor else '')])


def card_swap(leaving, arriving, factor=None):
    """Swaps any two of a window (0x…) and a card (its id): this also takes a card out of its tile whole."""
    def members(item):
        if str(item).startswith('0x'): return [item]
        return [a for c in ipc.status()['containers'] if c['id'] == item for face in c['faces'] for a in face]
    def relocate(item, to):
        return move(item, to) if str(item).startswith('0x') else f'hyprflip card {item} workspace {to} silent'
    return ([set_prop(a, 'no_anim', 'true') for a in (*members(leaving), *members(arriving))]
            + [f'hyprflip card {leaving} hold', relocate(leaving, PARK), relocate(arriving, PLACE),
               f'hyprflip card {arriving} reveal' + (f' {factor}' if factor else '')])


def record(commands, seconds=.6):
    """The frames rendered during a batch and the time after it. Each has every window's box and fade."""
    ipc.call('hf-motion-probe', 'start windows')
    batch(*commands)
    time.sleep(seconds)
    frames = json.loads(ipc.call('hf-motion-probe', 'stop'))
    assert frames, 'No frames were rendered'
    return frames


def of(frames, address):
    """Each frame's record of a window, once it was in the tile."""
    return [(f['ms'], next(win for win in f['windows'] if win['address'] == address)) for f in frames
            if any(win['address'] == address for win in f['windows'])]


def same(a, b, by=.01): return all(abs(x - y) <= by for x, y in zip(a, b))


def settled_ms(frames, address):
    """From its first frame in the tile to the last that still differs by half a pixel or a thousandth of its fade."""
    moving = [ms for ms, win in of(frames, address) if not same(win['box'], win['goal'], .5) or win['fade'] < .999]
    assert moving, 'It never animated'
    return moving[-1] - moving[0]


def opens(frames, address, goal):
    """A real open: the box from about 92% to the goal, the fade only rising, ending exactly there."""
    shown = [(ms, win) for ms, win in of(frames, address) if win['goal'] == goal]
    assert shown, (address, goal)
    scales = [win['box'][2] / goal[2] for _, win in shown]
    fades = [win['fade'] for _, win in shown]
    assert .905 <= scales[0] <= .95, scales[:4]
    assert all(b >= a - 1e-3 for a, b in zip(scales, scales[1:])), scales
    assert fades[0] < .5 and all(b >= a - 1e-3 for a, b in zip(fades, fades[1:])), fades
    # The last frame drawn can be a tick short of the end. hyprctl clients gives the end itself.
    assert same(shown[-1][1]['box'], goal) and fades[-1] > .999, shown[-1]


def pixel(x, y):
    """A screen pixel of the test output, in its layout's coordinates."""
    image = subprocess.run(['grim', '-t', 'ppm', '-g', f"{int(x)},{int(y)} 1x1", '-'], env=env,
                           check=True, capture_output=True, timeout=6).stdout
    return tuple(image[-3:])


def near(a, b, by=40): return max(abs(x - y) for x, y in zip(a, b)) <= by


def build_card(front, back, company):
    """A card on the test workspace with two apps on the side it shows and one on the side it hides."""
    focus(front); ipc.action('mark'); focus(back); ipc.action('card')
    focus(company); ipc.action('mark'); focus(back); ipc.action('attach')
    wait(lambda: not ipc.status()['animating'])
    return card_of(back)['id']


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    session_windows(env)
    shutil.copy2(project / 'build/hyprflip.so', library)
    shutil.copy2(project / 'build/motion_probe.so', probe)
    ipc.call('plugin', 'load', str(library)); loaded = library
    ipc.call('plugin', 'load', str(probe)); probed = True
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    ipc.call('output', 'create', 'headless')
    spare = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names | {output})
    config.write_text(original + LOOK + f'''
hl.monitor({{output="{output}",mode="1920x1080@60",position="2000x0",scale=1}})
hl.monitor({{output="{spare}",mode="1280x720@60",position="4000x0",scale=1}})
hl.workspace_rule({{workspace="{PLACE}",monitor="{output}"}})
''')
    ipc.call('reload')
    assert not ipc.call('configerrors'), ipc.call('configerrors')
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    ipc.call('dispatch', f'hl.dsp.focus({{workspace={PLACE}}})')

    assert ipc.status()['reveal'] is True
    passed('status says "reveal":true')

    # The tile that keeps working, and the two windows that take turns beside it.
    tile = spawn('tile', '203040')
    first = spawn('first', '0a6f8f')
    focus(tile)
    second = spawn('second', 'c2601a')
    batch(move(second, PARK))
    focus(tile)
    time.sleep(.5)
    goal = box(first)
    assert goal[0] > box(tile)[0], (goal, box(tile))
    tile_box = box(tile)

    # Refusals, each with a clear reply and no notification of either kind.
    notify_log.write_text('')
    before = ipc.status()
    for request, reply in (('card 999999 hold', 'error: No card has id 999999. Read the ids from status.'),
                           ('card 999999 reveal', 'error: No card has id 999999. Read the ids from status.'),
                           ('card 12x leave', 'error: Use card <id or 0x address>'),
                           ('card 0 hold', 'error: Use card <id or 0x address>'),
                           ('card 0xdeadbeef hold', 'error: No window has address 0xdeadbeef.'),
                           ('card 0xzz reveal', 'error: Use card <id or 0x address>'),
                           (f'card {first} reveal 9', 'error: The speed of a reveal is a number from 0.05 to 4, not 9.'),
                           (f'card {first} reveal fast', 'error: The speed of a reveal is a number from 0.05 to 4, not fast.'),
                           (f'card {first} reveal nan', 'error: The speed of a reveal is a number from 0.05 to 4, not nan.'),
                           (f'card {first} reveal 0.7 more', 'error: Use card <id or 0x address>'),
                           (f'card {first} hold 0.7', 'error: Use card <id or 0x address>'),
                           (f'card {first} surfaces', 'error: Use card <id> flip')):
        result = subprocess.run(['hyprctl', 'hyprflip', request], env=env, capture_output=True, text=True, timeout=8)
        assert result.stdout.strip().startswith(reply), (request, result.stdout)
    assert not notify_log.read_text(), notify_log.read_text()
    for request in ('card 0 foo', 'card 0'):
        result = subprocess.run(['hyprctl', 'hyprflip', request], env=env, capture_output=True, text=True, timeout=8)
        assert 'hold|leave|reveal' in result.stdout, 'Card usage must include the animation verbs'
    assert fadeouts() == 0 and box(first) == goal and ipc.status()['containers'] == before['containers']
    passed('a bad id, address, speed or extra word is refused with a clear reply and no notification, and nothing changes')

    # Hold, then reveal: a real open, in its tile, that nothing else notices.
    moved = rest(first)
    focus(tile)
    assert pointer() != moved, 'A focus dispatch should warp the pointer'
    passed('a focus dispatch warps the pointer, so a pointer left where it rested means that nothing warped it')
    before = rest(first)
    frames = record(swap(first, second))
    opens(frames, second, goal)
    assert max(f['fadeouts'] for f in frames) == 1, 'One window, one picture'
    assert frames[-1]['fadeouts'] == 0 and fadeouts() == 0
    assert all(win['box'] == tile_box for _, win in of(frames, tile)), 'The neighbour moved'
    assert box(second) == goal and box(tile) == tile_box and ipc.windows()[first]['workspace']['name'] == PARK
    assert prop(second, 'no_anim') is False, 'The swap left its no_anim on'
    assert active() == tile and pointer() == before, (active(), pointer(), before)
    passed('hold then reveal: the box goes from about 92% to its goal and the fade only rises, no_anim comes off, '
           'and the neighbour, the focus and the pointer stay')

    # A user's rule wins over a reveal. Without the swap's own no_anim, it is the rule that says.
    still = spawn('still', '305030')
    batch(move(still, PARK))
    focus(tile)
    time.sleep(.3)
    frames = record(swap(second, still))
    assert all(win['box'] == win['goal'] and win['fade'] == 1 for _, win in of(frames, still)), 'A no_anim rule was overruled'
    assert prop(still, 'no_anim') is True and box(still) == goal and fadeouts() == 0
    batch(move(still, PARK), move(second, PLACE))
    focus(tile)
    time.sleep(.3)
    passed('a window rule of no_anim stays: the window comes in at once and no_anim still reads true')

    # The speed factor is the duration's, and each comes from the user's animation untouched.
    times = {}
    a, b = second, first
    for factor in (None, '0.7', '2', None, '0.7'):
        frames = record(swap(a, b, factor), 1.1)
        opens(frames, b, goal)
        times.setdefault(factor, []).append(settled_ms(frames, b))
        a, b = b, a
    print('settled ms by factor', times, flush=True)
    full = sorted(times[None])[0]
    assert 150 < full < 650, times
    assert all(abs(t - full) < 34 for t in times[None]), times
    assert all(.55 < t / full < .85 for t in times['0.7']), times
    assert all(1.6 < t / full < 2.4 for t in times['2']), times
    leaving, arriving = a, b
    passed('the speed factor scales the duration, and the next reveal at the user\'s speed takes as long as the first')

    # A hold with nothing after it.
    before_box = box(leaving)
    batch(f'hyprflip card {leaving} hold')
    wait(lambda: fadeouts() == 0, 2)
    assert box(leaving) == before_box and prop(leaving, 'no_anim') is False
    batch(set_prop(leaving, 'no_anim', 'true'), f'hyprflip card {leaving} hold', move(leaving, PARK))
    wait(lambda: fadeouts() == 0, 2)
    time.sleep(.7)
    x, y, width, height = goal
    # The neighbour has grown across the empty place, with no picture over it.
    assert near(pixel(x + width // 2, y + height // 2), (0x20, 0x30, 0x40), 12), 'A picture stayed'
    batch(move(leaving, PLACE), f'hyprflip card {leaving} reveal')
    time.sleep(.7)
    assert box(leaving) == goal and box(tile) == tile_box and fadeouts() == 0
    passed('a hold with no reveal leaves nothing behind, with the window in place or moved away')

    # A close animation without an arriving window: the picture goes away, the real window stays mapped and parked.
    before = rest(tile)
    notices = notify_log.read_text()
    frames = record([set_prop(leaving, 'no_anim', 'true'), f'hyprflip card {leaving} leave', move(leaving, PARK)], .8)
    assert max(f['fadeouts'] for f in frames) == 1 and frames[-1]['fadeouts'] == 0 and fadeouts() == 0
    assert ipc.windows()[leaving]['workspace']['name'] == PARK
    assert active() == tile and pointer() == before and notify_log.read_text() == notices
    batch(move(leaving, PLACE), f'hyprflip card {leaving} reveal')
    time.sleep(.7)
    assert box(leaving) == goal and box(tile) == tile_box and fadeouts() == 0
    passed('leave closes a window through one temporary picture, keeps it mapped and parked, and leaves focus and pointer alone')

    # no_blur: lifted for the fade over a picture, then just as it was.
    ruled = spawn('ruled', '503050')
    batch(move(ruled, PARK))
    focus(tile)
    time.sleep(.3)
    batch(set_prop(arriving, 'no_blur', 'true'))
    batch(*swap(leaving, arriving))
    time.sleep(.7)
    assert prop(arriving, 'no_blur') is True, 'A no_blur set before was lost'
    batch(set_prop(arriving, 'no_blur', 'false'))
    batch(*swap(arriving, ruled, 2))
    time.sleep(1.3)
    assert prop(ruled, 'no_blur') is True, 'A rule of no_blur was lost'
    batch(set_prop(ruled, 'no_blur', 'false'))
    batch(*swap(ruled, arriving))
    time.sleep(.7)
    batch(*swap(arriving, ruled, 2))
    time.sleep(.1)
    assert prop(ruled, 'no_blur') is True, 'An opaque window goes without blur for the fade over a picture'
    # Back out and in again while it fades: what it had before still comes back.
    batch(*swap(ruled, arriving, 2))
    batch(*swap(arriving, ruled, 2))
    time.sleep(1.3)
    assert prop(ruled, 'no_blur') is False, 'A set_prop of no_blur false did not come back over the rule'
    batch(*swap(ruled, arriving))
    time.sleep(.7)
    assert prop(arriving, 'no_blur') is False
    leaving, arriving = arriving, leaving
    passed('no_blur set before a reveal stays set after: true, and false over a rule of true, through a fade and a return in mid-fade')

    # Rapid switching.
    pair = [leaving, arriving]
    ipc.call('hf-motion-probe', 'start windows')
    for number in range(9):
        batch(*swap(pair[number % 2], pair[(number + 1) % 2], '0.7'))
        time.sleep(.016)
    wait(lambda: fadeouts() == 0, 3)
    time.sleep(.5)
    frames = json.loads(ipc.call('hf-motion-probe', 'stop'))
    assert max(f['fadeouts'] for f in frames) <= 2, 'Rapid switching keeps the oldest and newest pictures only'
    assert frames[-1]['fadeouts'] == 0
    leaving, arriving = pair[1], pair[0]
    assert box(leaving) == goal and box(tile) == tile_box and ipc.windows()[arriving]['workspace']['name'] == PARK
    assert prop(leaving, 'no_anim') is False and prop(leaving, 'no_blur') is False
    assert active() == tile
    passed('9 batches at 16 ms keep at most two pictures, then none, and end with the last window right')

    # Cards. Each has two apps on the side it shows and one on the side it hides.
    batch(move(leaving, PARK))
    focus(tile)
    panes = [spawn(name, color) for name, color in (('c1', '0a6f8f'), ('c2', '0a6f8f'), ('c3', '00ff00'))]
    one = build_card(panes[0], panes[1], panes[2])
    usage = subprocess.run(['hyprctl', 'hyprflip', f'card {one} foo'], env=env, capture_output=True, text=True, timeout=8)
    assert 'hold|leave|reveal' in usage.stdout, 'Known-card usage must include the animation verbs'
    focus(tile)
    time.sleep(.3)
    one_shown = [a for a in card_of(panes[1])['faces'][card_of(panes[1])['active']]]
    assert len(one_shown) == 2, card_of(panes[1])
    one_boxes, one_frame = {a: box(a) for a in one_shown}, frame_of(one)
    panes2 = []
    batch(f'hyprflip card {one} workspace {PARK} silent')
    focus(tile)
    panes2 = [spawn(name, color) for name, color in (('d1', 'c2601a'), ('d2', 'c2601a'), ('d3', '00ff00'))]
    two = build_card(panes2[0], panes2[1], panes2[2])
    assert 'Card created' in notify_log.read_text(), 'The recorder should have seen the menu-less build, so its silence above means something'
    focus(tile)
    time.sleep(.3)
    two_shown = [a for a in card_of(panes2[1])['faces'][card_of(panes2[1])['active']]]
    two_boxes, two_frame = {a: box(a) for a in two_shown}, frame_of(two)
    assert two_frame['box'] == one_frame['box'], (two_frame, one_frame)

    before = rest(tile)
    frames = record(card_swap(two, one))
    for address in one_shown: opens(frames, address, one_boxes[address])
    scales = [[win['box'][2] / one_boxes[a][2] for a in one_shown for win in [next(x for x in f['windows'] if x['address'] == a)]]
              for f in frames if all(next(x for x in f['windows'] if x['address'] == a)['goal'] == one_boxes[a] for a in one_shown)]
    assert all(abs(s[0] - s[1]) < .002 for s in scales), 'The panes scale as one'
    assert max(f['fadeouts'] for f in frames) == 2 and fadeouts() == 0
    shown_frames = [next((c for c in f['state']['card_frames'] if c['id'] == one), None) for f in frames]
    assert all(c['box'] == one_frame['box'] for c in shown_frames if c), 'The frame moved over a header'
    assert {a: box(a) for a in one_shown} == one_boxes and frame_of(one)['box'] == one_frame['box']
    assert all(ipc.windows()[a]['workspace']['name'] == PARK for a in two_shown)
    assert active() == tile and pointer() == before and box(tile) == tile_box
    assert all(prop(a, 'no_anim') is False for a in one_shown)
    passed('a card over a card: its panes open as one, its frame stays still, two pictures come and go, '
           'and the neighbour, the focus and the pointer stay')

    # A reveal with a direction slides: in from below (up) or above (down), with no fade, while the picture of what
    # leaves goes the same way out of it.
    for bad in ('0.7 sideways', 'up 0.7', 'up down', 'sideways'):
        reply = subprocess.run(['hyprctl', 'hyprflip', f'card {one} reveal {bad}'], env=env, capture_output=True, text=True, timeout=8).stdout
        assert reply.startswith('error:') and ('[up|down]' in reply or 'speed' in reply), (bad, reply)
    assert ipc.status().get('reveal_slide') is True
    for out, into, shown, boxes, way in ((one, two, two_shown, two_boxes, 'up'), (two, one, one_shown, one_boxes, 'down')):
        before = rest(tile)
        frames = record(card_swap(out, into, f'0.7 {way}'))
        for a in shown:
            target = boxes[a]
            path = [win for _, win in of(frames, a) if win['goal'] == target]
            assert path, (a, way)
            ys = [win['box'][1] for win in path]
            card_height = max(b[1] + b[3] for b in boxes.values()) - min(b[1] for b in boxes.values())
            start = ys[0] - target[1]
            assert (start > card_height * .6) if way == 'up' else (start < -card_height * .6), (way, start, card_height)
            steps = list(zip(ys, ys[1:]))
            assert all((b <= a + .5) if way == 'up' else (b >= a - .5) for a, b in steps), (way, ys)
            assert all(abs(win['box'][0] - target[0]) < .5 and same(win['box'][2:], target[2:], .5) for win in path), 'Only y moves'
            assert all(win['fade'] > .999 for win in path), 'A slide does not fade'
            assert same(path[-1]['box'], target, .5), path[-1]
        assert max(f['fadeouts'] for f in frames) >= 1 and fadeouts() == 0
        assert {a: box(a) for a in shown} == boxes
        assert active() == tile and pointer() == before and box(tile) == tile_box
        assert all(prop(a, 'no_anim') is False for a in shown)
    # A frame to look at: halfway through a slow slide up
    ipc.call('hf-motion-probe', 'start windows')
    batch(*card_swap(one, two, '4 up'))
    time.sleep(.55)
    output_box = next(m for m in ipc.data('-j', 'monitors') if m['name'] == output)
    subprocess.run(['grim', '-g', f"{output_box['x']},{output_box['y']} {output_box['width']}x{output_box['height']}", str(root / 'slide-mid.png')], env=env, timeout=6)
    time.sleep(2)
    ipc.call('hf-motion-probe', 'stop')
    assert {a: box(a) for a in two_shown} == two_boxes and fadeouts() == 0
    batch(*card_swap(two, one))
    time.sleep(.8)
    passed('reveal up and down slide a card in from below and from above with no fade, its picture goes out alongside, '
           'a bad direction is refused, and the neighbour, the focus and the pointer stay')

    before = rest(tile)
    notices = notify_log.read_text()
    frames = record([*[set_prop(a, 'no_anim', 'true') for a in card_of(panes[1])['faces'][0] + card_of(panes[1])['faces'][1]],
                     f'hyprflip card {one} leave', f'hyprflip card {one} workspace {PARK} silent'], .8)
    assert max(f['fadeouts'] for f in frames) == len(one_shown) and fadeouts() == 0
    assert card_of(panes[1])['workspace']['name'] == PARK
    assert active() == tile and pointer() == before and notify_log.read_text() == notices
    batch(f'hyprflip card {one} workspace {PLACE} silent', f'hyprflip card {one} reveal')
    time.sleep(.7)
    assert {a: box(a) for a in one_shown} == one_boxes and box(tile) == tile_box and fadeouts() == 0
    passed('leave snapshots only the shown face of a card, cleans every picture and keeps the parked card intact')

    # A plain window for a card and the reverse: the header band. A control for the second:
    # at rest, the button's pixel is the header's own.
    time.sleep(.3)
    x, y, width, height = one_frame['button']
    spot = x + 3, y + height // 2
    at_rest = pixel(*spot)
    assert not near(at_rest, WALLPAPER), at_rest
    batch(*card_swap(one, leaving, 4))
    time.sleep(.09)
    mid = pixel(*spot)
    print('button pixel: at rest', at_rest, 'a plain window replacing the card', mid, flush=True)
    assert near(mid, at_rest, 60), 'The header band has no picture under it'
    assert box(leaving) == goal
    wait(lambda: fadeouts() == 0, 3)
    time.sleep(1.6)
    assert box(leaving) == goal and fadeouts() == 0 and prop(leaving, 'no_anim') is False
    plain = pixel(*spot)
    assert not near(plain, WALLPAPER), plain
    time.sleep(.2)

    ipc.call('hf-motion-probe', 'start windows')
    batch(*card_swap(leaving, one, 4))
    time.sleep(.09)
    mid = pixel(*spot)
    print('button pixel: at rest', plain, 'a card replacing the plain window', mid, flush=True)
    assert near(mid, plain, 60) and not near(mid, at_rest, 30), 'The header came in ahead of its panes'
    time.sleep(.15)
    wait(lambda: fadeouts() == 0, 3)
    time.sleep(1.6)
    frames = json.loads(ipc.call('hf-motion-probe', 'stop'))
    shown_frames = [c for f in frames for c in f['state']['card_frames'] if c['id'] == one]
    assert shown_frames[0]['box'][2] < one_frame['box'][2] - 20, 'The frame should grow with its panes here'
    assert shown_frames[-1]['box'] == one_frame['box'] == frame_of(one)['box']
    assert {a: box(a) for a in one_shown} == one_boxes
    assert ipc.windows()[leaving]['workspace']['name'] == PARK
    assert near(pixel(*spot), at_rest, 8)
    passed('a plain window replacing a card keeps the header in its picture, and a card replacing a plain window brings the header in with its panes')

    # Rapid switching of cards, and a third that takes the place.
    pair = [one, two]
    ipc.call('hf-motion-probe', 'start windows')
    for number in range(9):
        batch(*card_swap(pair[number % 2], pair[(number + 1) % 2], '0.7'))
        time.sleep(.016)
    wait(lambda: fadeouts() == 0, 3)
    time.sleep(.5)
    frames = json.loads(ipc.call('hf-motion-probe', 'stop'))
    assert max(f['fadeouts'] for f in frames) <= 4
    assert {a: box(a) for a in two_shown} == two_boxes and frame_of(two)['box'] == two_frame['box'] and box(tile) == tile_box
    assert all(prop(a, 'no_anim') is False for a in two_shown) and active() == tile
    passed('9 card batches at 16 ms keep at most four pictures of two panes, then none, and end with the last card right')

    # A config reload during a reveal.
    batch(*card_swap(two, leaving, 4))
    time.sleep(.1)
    ipc.call('reload')
    assert not ipc.call('configerrors')
    wait(lambda: fadeouts() == 0, 3)
    time.sleep(1.6)
    assert box(leaving) == goal and box(tile) == tile_box and prop(leaving, 'no_anim') is False
    assert prop(leaving, 'no_blur') is False and active() == tile
    frames = record(swap(leaving, arriving), .6)
    opens(frames, arriving, goal)
    leaving, arriving = arriving, leaving
    passed('a config reload during a reveal: it ends right, no_blur comes back, and the next reveal is a real open')

    # Plugin unload during a reveal. Its cards come apart, as they do in any unload.
    batch(*swap(leaving, arriving, 4))
    time.sleep(.1)
    assert fadeouts() >= 1
    ipc.call('plugin', 'unload', str(library)); loaded = None
    assert fadeouts() == 0, 'A picture of the plugin stayed in Hyprland\'s list'
    time.sleep(1.8)
    assert box(arriving) == goal and ipc.data('-j', 'monitors') and active() == tile
    assert prop(arriving, 'no_blur') is False
    batch(move(arriving, PARK))
    time.sleep(.7)
    assert near(pixel(goal[0] + goal[2] // 2, goal[1] + goal[3] // 2), (0x20, 0x30, 0x40), 12), 'The compositor stopped drawing'
    passed('plugin unload during a reveal: no picture stays, the window ends in its tile, and the compositor renders on')

    # A monitor removed with a picture up, then the plugin gone too: the prototype's crash.
    fresh = root / 'reveal-hyprflip-2.so'
    shutil.copy2(project / 'build/hyprflip.so', fresh)
    ipc.call('plugin', 'load', str(fresh)); loaded = fresh
    time.sleep(.2)
    batch(move(leaving, PLACE))
    time.sleep(.5)
    batch(*swap(leaving, arriving, 4))
    time.sleep(.05)
    assert fadeouts() == 1
    ipc.call('output', 'remove', output); gone, output = output, None
    wait(lambda: gone not in {m['name'] for m in ipc.data('-j', 'monitors')})
    assert fadeouts() == 0, 'The removed monitor\'s picture stayed'
    time.sleep(.5)
    assert all(win['monitor'] != -1 for a, win in ipc.windows().items() if a in (arriving, tile))
    ipc.call('plugin', 'unload', str(fresh)); loaded = None
    time.sleep(.4)
    assert ipc.data('-j', 'monitors') and fadeouts() == 0
    ipc.call('plugin', 'load', str(fresh)); loaded = fresh
    time.sleep(.2)
    batch(f'hyprflip card {arriving} hold')
    wait(lambda: fadeouts() == 0, 2)
    passed('a monitor removed with a picture up takes the picture with it, and an unload after that leaves a working compositor')
    print(f'{len(checks)} checks passed', flush=True)
finally:
    for process in processes:
        if process.poll() is None: process.terminate()
    for process in processes:
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=3)
    config.write_text(original)
    try:
        ipc.call('reload')
        if loaded: ipc.call('plugin', 'unload', str(loaded))
        if probed: ipc.call('plugin', 'unload', str(probe))
        for name in (output, spare):
            if name: ipc.call('output', 'remove', name)
    except w.SetupError as error:
        print('cleanup:', error, flush=True)
