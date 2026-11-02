#!/usr/bin/env python3
"""Updating the core with scripts/install.py keeps open native cards, leaves parked ones as separate windows,
and leaves the keyboard, the pointer and the monitors where they were, in a disposable compositor."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from control import environment, session_windows

project = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project / 'scripts'))
import workflow as w

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('session', type=Path)
args = parser.parse_args()
root = args.session.parent
home = root / 'install-home'
(home / '.config/hypr').mkdir(parents=True, exist_ok=True)
(home / '.config/hypr/hyprland.lua').write_text('-- disposable installer test configuration\n')
env = environment(args.session) | {'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
                                   'XDG_STATE_HOME': str(home / '.local/state'), 'XDG_DATA_HOME': str(home / '.local/share')}
ipc = w.Hyprctl(env)
config = root / 'hyprland.lua'
original = config.read_text()
processes, checks, failed = [], [], []
library = home / '.local/lib/hyprflip/hyprflip.so'
output = None


def passed(message):
    checks.append(message)
    print('PASS', message, flush=True)


def check(message, body):
    """A check that stands alone: a failure names what broke, the windows it opened close, and the next check still runs."""
    mark = len(processes)
    try:
        body()
    except Exception as error:
        failed.append(message)
        print('FAIL', message, repr(error), flush=True)
    else:
        passed(message)
    finally:
        clear(mark)


def wait(fn):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if fn(): return
        time.sleep(.05)
    raise AssertionError(ipc.status())


def spawn(name):
    app = 'hyprflip-install-' + name
    processes.append(subprocess.Popen(['foot', '--config', '/dev/null', '--app-id', app, 'cat'], env=env,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    wait(lambda: any(win['class'] == app for win in ipc.windows().values()))
    return next(a for a, win in ipc.windows().items() if win['class'] == app)


def install(refused=None):
    """An update, in which every request that says `refused` gets the answer of a Hyprland that stopped answering."""
    run = env
    if refused:
        shim = root / 'shim'
        shim.mkdir(exist_ok=True)
        (shim / 'hyprctl').write_text(f"""#!/bin/sh
case "$*" in *'{refused}'*) echo "Couldn't read (6)"; exit 6;; esac
exec {shutil.which('hyprctl')} "$@"
""")
        (shim / 'hyprctl').chmod(0o755)
        run = env | {'PATH': f'{shim}:{env["PATH"]}'}
    result = subprocess.run(['python3', str(project / 'scripts/install.py')], env=run, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (result.stdout, result.stderr)
    return result.stdout


def active(): return ipc.data('-j', 'activewindow').get('address')


def tile(address):
    window = ipc.windows()[address]
    return [*window['at'], *window['size']]


def pointer():
    at = ipc.data('-j', 'cursorpos')
    return at['x'], at['y']


def rest(over):
    """Leaves the pointer off-centre over a window, where a warp to any window's centre shows."""
    x, y, width, height = tile(over)
    point = x + width // 4, y + height // 3
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={point[0]},y={point[1]}}})')
    assert pointer() == point, (over, point, pointer())
    return point


def shown():
    """What each monitor shows, an open special workspace included, and which of them has the focus."""
    monitors = ipc.data('-j', 'monitors')
    return ({m['name']: (m['activeWorkspace']['id'], m['specialWorkspace']['name']) for m in monitors},
            next(m['name'] for m in monitors if m['focused']))


def shape(card):
    keys = ('faces', 'active', 'unfolded', 'floating', 'layouts', 'native_group')
    described = {k: card.get(k) for k in keys}
    described['layouts'] = [{'axis': l['axis'], 'focused': l['focused'], 'ratios': [round(r, 3) for r in l['ratios']]}
                            for l in card['layouts']]
    return described


def open_cards():
    """Each card on a regular workspace, by its apps: its shape and its frame."""
    return {tuple(x for f in card['faces'] for x in f): (shape(card), card['box']) for card in ipc.status()['containers']
            if not card['workspace']['special']}


class Moves:
    """Which workspaces came to be shown, by name, and which windows got the keyboard, as Hyprland's event socket said."""
    def __init__(self):
        self.seen = []
        events = Path(env['XDG_RUNTIME_DIR']) / 'hypr' / env['HYPRLAND_INSTANCE_SIGNATURE'] / '.socket2.sock'
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.connection.connect(str(events))
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        pending = b''
        while chunk := self.connection.recv(65536):
            *lines, pending = (pending + chunk).split(b'\n')
            # Only names and addresses: other events carry window titles.
            for line in lines:
                if line.startswith(b'workspace>>'):
                    self.seen.append(line.removeprefix(b'workspace>>').decode())
                elif line.startswith(b'activewindowv2>>'):
                    self.seen.append('0x' + line.removeprefix(b'activewindowv2>>').decode())


moves = None


def update(keyboard, corrects=None, tiles=True, focused=None):
    """An update: the cards come back as they were, and the keyboard, the pointer and the monitors stay.

    `corrects` is the hidden workspace or the window that a tile correction must
    have shown or focused on the way, so that the check cannot pass with nothing
    to put back. `tiles` is False for a layout that does not come back as it was.
    `focused` is the monitor that has the focus afterwards, for a pointer on
    another monitor than the keyboard, as the focus that gives the keyboard back
    brings it along. The update says nothing of what is as it was.
    """
    before, at, monitors = open_cards(), pointer(), shown()
    assert active() == keyboard, (keyboard, active())
    mark = len(moves.seen)
    out = install()
    assert f'Keeping {len(before)} open card(s)' in out, out
    time.sleep(.3)
    visits = moves.seen[mark:]
    print('update: pointer', at, pointer(), 'monitors', monitors, shown(), 'keyboard kept', active() == keyboard,
          'moves', visits, flush=True)
    assert (pointer(), shown(), active()) == (at, (monitors[0], focused or monitors[1]), keyboard), (at, pointer(), monitors, shown(), keyboard, active())
    assert 'not as it was' not in out, out
    assert not tiles or 'A card was kept' not in out, out
    after = open_cards()
    assert set(after) == set(before), (before, after)
    for members, (described, box) in before.items():
        assert after[members][0] == described, (described, after[members][0])
        assert not tiles or all(abs(p - q) <= 4 for p, q in zip(after[members][1], box)), (described['floating'], box, after[members][1])
    assert corrects is None or str(corrects) in visits, (corrects, visits)
    return out


def to_workspace(number):
    ipc.call('dispatch', f'hl.dsp.focus({{workspace={number}}})')


def to_monitor(name):
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{name}"}})')


def give_keyboard(address):
    ipc.call('dispatch', w.Unattended.focus_command(address))
    wait(lambda: active() == address)


def card_of(member):
    return next(card for card in ipc.status()['containers'] if member in sum(card['faces'], []))


def named_window(name):
    return next(a for a, window in ipc.windows().items() if window['class'] == 'hyprflip-install-' + name)


def over_monitor(monitor):
    """The pointer over a monitor, off-centre, where a new tile lands the same way each time."""
    at = next(m for m in ipc.data('-j', 'monitors') if m['name'] == monitor)
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={at["x"] + 300},y={at["y"] + 400}}})')


def clear(mark):
    """Closes the windows opened since `mark`, and with them the cards they made."""
    addresses = {address for address, window in ipc.windows().items() if window['pid'] in {p.pid for p in processes[mark:]}}
    for process in processes[mark:]:
        process.terminate()
    wait(lambda: not addresses & set(ipc.windows()))


def two_on_a_face(workspace, tag):
    """A card alone on a workspace: one app on its hidden side, two on the side it shows."""
    to_workspace(workspace)
    hidden, left, right = spawn(tag + '-hidden'), spawn(tag + '-left'), spawn(tag + '-right')
    ipc.focused((hidden, 'mark'), (left, 'card')); ipc.focused((right, 'mark'), (left, 'attach horizontal'))
    assert sorted(card_of(left)['faces'][card_of(left)['active']]) == sorted((left, right)), card_of(left)
    return left, right


def stacked(workspace, tag):
    """A card as the second tile of a workspace, in the row below its neighbour. An update has to correct it."""
    to_workspace(workspace)
    spawn(tag + '-neighbour')
    front, back = spawn(tag + '-front'), spawn(tag + '-back')
    ipc.focused((front, 'mark'), (back, 'card'))
    give_keyboard(card_of(front)['current'])
    if card_of(front)['box'][3] > 1000:
        ipc.call('dispatch', 'hl.dsp.layout("togglesplit")')
    if card_of(front)['box'][1] < 100:
        ipc.call('dispatch', 'hl.dsp.layout("swapsplit")')
    x, y, width, height = card_of(front)['box']
    assert y > 100 and height < 1000, card_of(front)
    return front


def a_card_alone():
    # Unloading the core drops the keyboard from every app of a multi-app face but one.
    left, right = two_on_a_face(92, 'alone')
    for keyboard in (left, right, left):
        give_keyboard(keyboard)
        rest(right)
        update(keyboard)
        assert len(open_cards()) == 1


def another_card_corrected_beside_it(on_app, pointer_over=None):
    """The keyboard on one app of a two-app face, and a card built before it that needs a correction, on one workspace.

    The first correction takes the keyboard, and no visit to another workspace
    gives it back here, as coming back from one does. A card on the left half, and
    on the right a neighbour with a card in the row below it: no layout with two
    more tiles comes back as it was (see TESTING.md). With the pointer on another
    monitor, the monitor that the correction gives the focus back to hands the
    keyboard to its own window unless it went back first.
    """
    to_workspace(93)
    hidden = spawn('beside-hidden')
    x, y, width, height = tile(hidden)
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={x + width - 40},y={y + height // 2}}})')
    neighbour = spawn('beside-neighbour')
    x, y, width, height = tile(neighbour)
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={x + width // 2},y={y + height - 40}}})')
    front, back = spawn('beside-front'), spawn('beside-back')
    ipc.focused((front, 'mark'), (back, 'card'))
    x, y, width, height = tile(hidden)
    ipc.call('dispatch', f'hl.dsp.cursor.move({{x={x + width // 2},y={y + height // 2}}})')
    give_keyboard(hidden)
    apps = spawn('beside-left'), spawn('beside-right')
    ipc.focused((hidden, 'mark'), (apps[0], 'card')); ipc.focused((apps[1], 'mark'), (apps[0], 'attach horizontal'))
    assert ipc.status()['containers'][0] == card_of(front), ipc.status()['containers']
    give_keyboard(apps[on_app])
    rest(pointer_over or neighbour)
    update(apps[on_app], corrects=card_of(front)['current'], tiles=False, focused=output if pointer_over else None)


def two_cards_alone(workspace, tag, apps, turned):
    """Two tiled cards and nothing else on a workspace: a correction next to loose tiles squeezes one to a sliver.

    Updated from another workspace, where a correction shows theirs, then with the
    keyboard on one and the pointer over the other, twice.
    """
    to_monitor(output)
    to_workspace(97)
    over_monitor(output)
    elsewhere = spawn(tag + '-elsewhere')
    to_workspace(workspace)
    over_monitor(output)
    fronts = []
    for name, count in zip('ab', apps):
        hidden, *showing = [spawn(f'{tag}-{name}{i}') for i in range(count)]
        ipc.focused((hidden, 'mark'), (showing[0], 'card'))
        for address in showing[1:]:
            ipc.focused((address, 'mark'), (showing[0], 'attach horizontal'))
        fronts.append(showing[0])
    time.sleep(.2)
    if turned:
        give_keyboard(card_of(fronts[1])['current'])
        ipc.call('dispatch', 'hl.dsp.layout("togglesplit")')
        time.sleep(.2)
    first_frames = {member: card_of(member)['box'] for member in fronts}
    assert sorted(card_of(front)['box'][2] > 2000 for front in fronts) in ([False, False], [True, True]), first_frames
    print('two cards', apps, 'turned' if turned else 'as they fell', first_frames, flush=True)
    to_workspace(97)
    give_keyboard(elsewhere)
    rest(elsewhere)
    update(elsewhere)
    to_workspace(workspace)
    keyboard = card_of(fronts[0])['current']
    give_keyboard(keyboard)
    rest(card_of(fronts[1])['current'])
    for _ in range(2):
        update(keyboard)
    for member, box in first_frames.items():
        assert all(abs(p - q) <= 4 for p, q in zip(card_of(member)['box'], box)), (box, card_of(member)['box'])


def beside_another_monitor(first):
    """Corrections and updates with the session's own monitor beside the headless one that has the cards."""
    session = next(a for a, window in ipc.windows().items() if window['class'] == 'hyprflip-front')
    to_monitor(output)
    to_workspace(97)
    elsewhere = spawn('elsewhere2')
    to_workspace(95)
    neighbor = spawn('neighbor2')
    front, back = spawn('front2'), spawn('back2')
    ipc.focused((front, 'mark'), (back, 'card'))
    # In a special workspace of its own, for whichever monitor opens it.
    over = spawn('over')
    ipc.call('dispatch', f'hl.dsp.window.move({{window="address:{over}",workspace="special:scratch",follow=false}})')
    time.sleep(.2)
    made = card_of(front)
    current, line, saved = made['current'], card_restore.describe(made), tuple(made['box'])
    described, beside_saved = shape(made), tile(neighbor)
    box = lambda: tuple(card_of(front)['box'])

    def no_focus(value):
        ipc.call('dispatch', f'hl.dsp.window.set_prop({{window="address:{current}",prop="no_focus",value="{value}"}})')

    def home():
        """Back to the scene after any check, a failed one too."""
        no_focus(0)
        for monitor in ipc.data('-j', 'monitors'):
            if monitor['specialWorkspace']['name']:
                to_monitor(monitor['name'])
                ipc.call('dispatch', 'hl.dsp.workspace.toggle_special("scratch")')
        wait(lambda: not any(special for _, special in shown()[0].values()))
        to_monitor(first)
        to_workspace(1)
        to_monitor(output)
        to_workspace(95)

    def displace():
        """Takes the card out of its tile, unless a failed check left it out."""
        home()
        give_keyboard(current)
        if sum(abs(p - q) for p, q in zip(box(), saved)) <= 50:
            for message in ('togglesplit', 'swapsplit'):
                ipc.call('dispatch', f'hl.dsp.layout("{message}")')
        assert sum(abs(p - q) for p, q in zip(box(), saved)) > 50, (saved, box())
        return box()

    def state():
        return pointer(), shown(), active()

    def is_back():
        """The card in its saved tile, with its faces, sides and layouts, and the neighbour in its own."""
        assert all(abs(p - q) <= 4 for p, q in zip(box(), saved)), (saved, box())
        assert all(abs(p - q) <= 4 for p, q in zip(tile(neighbor), beside_saved)), (beside_saved, tile(neighbor))
        assert shape(card_of(front)) == described, (described, shape(card_of(front)))

    def corrected(arrange):
        """A correction from the state `arrange` makes: the card is back, and nothing else differs."""
        displace()
        arrange()
        before = state()
        card_restore.settle(line)
        time.sleep(.2)
        print('corrected:', before, state(), flush=True)
        assert state() == before, (before, state())
        is_back()

    def left(arrange, reason, error):
        """A correction that gives up: the card stays out of its tile, and nothing else differs either."""
        displaced = displace()
        beside = tile(neighbor)
        arrange()
        before = state()
        try:
            card_restore.settle(line)
        except error as raised:
            assert reason in str(raised), raised
        else:
            raise AssertionError('settle went on')
        time.sleep(.2)
        print('left:', before, state(), flush=True)
        assert state() == before, (before, state())
        assert box() == displaced and tile(neighbor) == beside, (displaced, box(), beside, tile(neighbor))
        assert shape(card_of(front)) == described, (described, shape(card_of(front)))

    def on(workspace, keyboard, pointer_over=None):
        def arrange():
            to_workspace(workspace)
            give_keyboard(keyboard)
            rest(pointer_over or keyboard)
        return arrange

    def on_nothing(monitor, workspace):
        def arrange():
            to_monitor(monitor)
            to_workspace(workspace)
            wait(lambda: active() is None)
            # Off the tiles' middle, where a restore's new tile lands away from where it was.
            x, y = next((m['x'], m['y']) for m in ipc.data('-j', 'monitors') if m['name'] == monitor)
            ipc.call('dispatch', f'hl.dsp.cursor.move({{x={x + 300},y={y + 400}}})')
        return arrange

    def special(monitor, under, keyboard):
        """The special workspace open on a monitor over a workspace, and the keyboard in it or on another window."""
        def arrange():
            to_monitor(output)
            to_workspace(under if monitor == output else 97)
            to_monitor(monitor)
            ipc.call('dispatch', 'hl.dsp.workspace.toggle_special("scratch")')
            wait(lambda: shown()[0][monitor][1] == 'special:scratch')
            give_keyboard(keyboard)
            rest(keyboard)
        return arrange

    def refused(*lastly):
        """The card takes no keyboard, and another window of its workspace, or none, was last focused there."""
        def arrange():
            no_focus(1)
            for address in lastly:
                give_keyboard(address)
        return arrange

    def both(*arrangers):
        return lambda: [arrange() for arrange in arrangers]

    checks_of = {
        'on another workspace of its monitor': on(97, elsewhere),
        'on the other monitor, with the card hidden': on(97, session),
        'on the other monitor, with the card shown': on(95, session),
        'on nothing, on an empty workspace of its monitor': on_nothing(output, 98),
        'on nothing, on an empty workspace of the other monitor, with the card shown': on_nothing(first, 50),
    }
    for where, arrange in checks_of.items():
        check(f'a correction with the keyboard {where} changes nothing else', lambda: corrected(arrange))

    def pointer_elsewhere():
        # A warp over the other monitor gives that monitor the focus and leaves the
        # keyboard. Only a focus can give the keyboard back, and it brings that focus along.
        displace()
        on(97, elsewhere, session)()
        before = state()
        assert before[1][1] == first and before[2] == elsewhere, before
        card_restore.settle(line)
        time.sleep(.2)
        print('corrected:', before, state(), flush=True)
        assert state() == (before[0], (before[1][0], output), elsewhere), (before, state())
        is_back()
    check('a correction with the pointer over the other monitor from the keyboard changes only which monitor has the focus, '
          'which goes with the keyboard', pointer_elsewhere)

    for hide in ('true', 'false'):
        ipc.call('eval', f'hl.config({{binds={{hide_special_on_workspace_change={hide}}}}})')
        assert ipc.data('-j', 'getoption', 'binds:hide_special_on_workspace_change')['bool'] is (hide == 'true')
        for where, arrange in {
                'in a special workspace open over another workspace of its monitor': special(output, 97, over),
                'in a special workspace open over the card': special(output, 95, over),
                'on the other monitor, with a special workspace open over another workspace of the card\'s': special(output, 97, session),
                'on the other monitor, with a special workspace open over the card': special(output, 95, session),
                'in a special workspace open on the other monitor': special(first, 97, over),
                # Showing an empty workspace hands the focus to the monitor under the pointer.
                'on the other monitor, with the pointer, and a special workspace open over an empty workspace of the card\'s': special(output, 98, session)}.items():
            check(f'a correction with the keyboard {where} changes nothing else (hide_special_on_workspace_change {hide})',
                  lambda: corrected(arrange))
        check(f'a correction with the keyboard in a special workspace open over an empty workspace, and the pointer over the other monitor, '
              f'opens it on its own monitor and changes nothing else (hide_special_on_workspace_change {hide})',
              lambda: corrected(both(special(output, 98, over), lambda: rest(session))))
    ipc.call('eval', 'hl.config({binds={hide_special_on_workspace_change=true}})')
    for where, arrange in {
            'another workspace of its monitor': both(refused(), on(97, elsewhere)),
            'another workspace of its monitor, after a neighbour had the keyboard there': both(refused(neighbor), on(97, elsewhere)),
            'the other monitor': both(refused(neighbor), on(97, session))}.items():
        check(f'a card that refuses the keyboard stays out of its tile, and with the keyboard on {where} nothing else changes',
              lambda: left(arrange, 'did not take the keyboard', RuntimeError))
    for where, monitor in (('the card\'s monitor', output), ('the other monitor', first)):
        def named():
            to_monitor(monitor)
            ipc.call('dispatch', 'hl.dsp.focus({workspace="name:hf"})')
            wait(lambda: active() is None)
        check(f'with a named workspace on {where} the card stays out of its tile, as nothing could show that workspace again',
              lambda: left(named, 'Not a numbered workspace', ValueError))

    def no_saved_size():
        # An update run under a fullscreen window saves a tile that reads as no size.
        displaced = displace()
        on(97, elsewhere)()
        before = state()
        parts = line.split()
        parts[3:7] = ['0'] * 4
        card_restore.settle(' '.join(parts))
        time.sleep(.2)
        assert state() == before and box() == displaced, (before, state(), displaced, box())
    check('a card saved with a tile of no size is left where it is, and nothing else changes', no_saved_size)

    # With special_fallthrough on, a focus of a window under an open special workspace
    # leaves that open, and dwindle's controls do not move the card under it.
    ipc.call('eval', 'hl.config({input={special_fallthrough=true}})')
    assert ipc.data('-j', 'getoption', 'input:special_fallthrough')['bool'] is True
    check('with special_fallthrough on and the keyboard in a special workspace over the card, the card and its neighbour stay where they are',
          lambda: left(special(output, 95, over), 'not back in its tile', RuntimeError))
    check('with special_fallthrough on and the keyboard on the other monitor, a correction under a special workspace changes nothing else',
          lambda: corrected(special(output, 95, session)))
    ipc.call('eval', 'hl.config({input={special_fallthrough=false}})')

    def session_tiles():
        return {a: tile(a) for a, window in ipc.windows().items() if window['workspace']['id'] == 1}

    def focus_moves_during(word, target):
        """The focus moves to the other monitor just before a step: no step rearranges a window there, and it stays."""
        displace()
        on(95, neighbor)()
        tiles, at = session_tiles(), pointer()
        assert session in tiles and len(tiles) > 1, tiles
        pending = [word]
        after_it = []

        def moving(*args):
            if not pending or args[0] != 'dispatch' or word not in args[1]:
                return card_restore.ctl(*args)
            pending.clear()
            give_keyboard(session)
            reply = card_restore.ctl(*args)
            # Right after it: settle's undo of a step that brought it no closer would hide what it did.
            after_it.append(session_tiles())
            return reply
        try:
            card_restore.settle(target, ctl=moving)
        except RuntimeError as error:
            assert 'not back in its tile' in str(error), error
        else:
            raise AssertionError('settle says the card is back')
        time.sleep(.2)
        assert not pending, word
        assert (active(), pointer()) == (session, at), (session, active(), at, pointer())
        assert shown() == ({first: (1, ''), output: (95, '')}, first), shown()
        assert after_it == [tiles] and session_tiles() == tiles, (tiles, after_it, session_tiles())

    # A size the card does not have, so that a resize is due once it is in its corner.
    parts = line.split()
    parts[5] = f'{float(parts[5]) - 100:.12g}'
    narrower = ' '.join(parts)
    for word, target in (('togglesplit', line), ('swapsplit', line), ('resize', narrower)):
        check(f'a focus that moves just before a correction\'s {word} stops it, and no tile of the window that took it moves',
              lambda: focus_moves_during(word, target))

    def monitor_goes():
        """A monitor goes away at the first step, and takes the focus along: the steps stop, and no resize squeezes a tile."""
        names = {m['name'] for m in ipc.data('-j', 'monitors')}
        ipc.call('output', 'create', 'headless')
        third = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
        pending = [third]

        def removing(*args):
            if pending and args[0] == 'dispatch' and 'togglesplit' in args[1]:
                pending.clear()
                ipc.call('output', 'remove', third)
                time.sleep(.3)
            return card_restore.ctl(*args)
        try:
            displace()
            on(97, session)()
            try:
                card_restore.settle(line, ctl=removing)
            except RuntimeError as error:
                assert 'not back in its tile' in str(error), error
            time.sleep(.2)
            assert not pending
            print('a monitor went:', box(), tile(neighbor), state(), flush=True)
            assert active() == session, (session, active())
            assert min(box()[2:] + tuple(tile(neighbor)[2:])) > 500, (box(), tile(neighbor))
        finally:
            if pending:
                ipc.call('output', 'remove', third)
    check('a monitor that goes away during a correction leaves the keyboard where it was and no tile a sliver', monitor_goes)

    def fullscreen_stays(policy, mode, state_value):
        """A window on the card's workspace fullscreen, with the keyboard, then hidden with the keyboard elsewhere."""
        with_options(f'hl.config({{misc={{on_focus_under_fullscreen={policy}}}}})')
        try:
            assert ipc.data('-j', 'getoption', 'misc:on_focus_under_fullscreen')['int'] == policy
            home()
            tag = f'fs{policy}{mode[0]}'
            shows = stacked(91, tag)
            beside = named_window(tag + '-neighbour')
            give_keyboard(beside)
            ipc.call('dispatch', f'hl.dsp.window.fullscreen({{mode="{mode}"}})')
            wait(lambda: ipc.windows()[beside]['fullscreen'] == state_value)
            rest(beside)
            word = 'A card was kept, but a fullscreen window on its workspace kept its tile from being checked or returned.'

            def stayed():
                assert ipc.windows()[beside]['fullscreen'] == state_value, ipc.windows()[beside]['fullscreen']

            def toggle(to):
                to_workspace(91)
                give_keyboard(beside)
                ipc.call('dispatch', f'hl.dsp.window.fullscreen({{mode="{mode}"}})')
                wait(lambda: ipc.windows()[beside]['fullscreen'] == to)
                time.sleep(.2)
            out = update(beside, tiles=False)
            assert word in out, out
            stayed()
            # Leaving it, the tile is what the rebuild made it: no sliver, and the card whole.
            toggle(0)
            print('after fullscreen:', card_of(shows)['box'], tile(beside), flush=True)
            assert min(card_of(shows)['box'][2:] + tile(beside)[2:]) > 500, (card_of(shows)['box'], tile(beside))
            # Hidden, with the keyboard elsewhere.
            toggle(state_value)
            to_workspace(97)
            give_keyboard(elsewhere)
            rest(elsewhere)
            out = update(elsewhere, tiles=False)
            assert word in out, out
            stayed()
            # Run again before it ends, the saved tile has no size to go back to, and nothing visits the workspace.
            mark = len(moves.seen)
            out = update(elsewhere, tiles=False)
            assert word not in out and '91' not in moves.seen[mark:], (out, moves.seen[mark:])
            stayed()
        finally:
            with_options()
    for policy, mode, state_value in ((1, 'fullscreen', 2), (0, 'fullscreen', 2), (2, 'fullscreen', 2), (1, 'maximized', 1)):
        check(f'a {mode} window on a card\'s workspace stays so through an update, which says it left that tile alone '
              f'(on_focus_under_fullscreen {policy})', lambda: fullscreen_stays(policy, mode, state_value))

    # Whole updates, with a second card that needs its tile corrected on a hidden workspace.
    home()
    try:
        card_restore.settle(line)
    except RuntimeError as error:
        # A failed check left it so. These compare before and after, and still run.
        print('The first card stays out of its tile:', error, flush=True)
    stacked(94, 'stacked')
    one, two = two_on_a_face(92, 'other')
    for where, keyboard, arrange in (
            ('on the other monitor', session, on(97, session)),
            ('on another workspace of that monitor', elsewhere, on(97, elsewhere)),
            ('on nothing, on an empty workspace', None, on_nothing(output, 98)),
            ('in a special workspace open over another workspace', over, special(output, 97, over)),
            ('on the first app of a two-app face of another card', one, on(92, one, one)),
            ('on the second app of a two-app face of another card', two, on(92, two, one)),
            ('on the first app of that face again', one, on(92, one, one))):
        def whole():
            home()
            arrange()
            update(keyboard, corrects=94)
        check(f'an update that corrects a card on a hidden workspace, with the keyboard {where}, changes nothing', whole)

    def says_so():
        home()
        on(97, elsewhere)()
        out = install(refused='workspace = 97')
        time.sleep(.3)
        assert 'The keyboard or what a monitor shows is not as it was before the update, or Hyprland did not say.' in out, out
        assert 'Installed and loaded' in out, out
        assert shown()[0][output][0] != 97 and active() != elsewhere, (shown(), active())
    check('an update whose way back fails goes on and says that the keyboard or a monitor is not as it was', says_so)
    home()


def with_options(lua=''):
    """Options that have to outlast an update's reload: the session's configuration with them."""
    config.write_text(settings + lua)
    ipc.call('reload')


def a_recovery_run():
    """A run after a crash between the unload and the restores: the core is gone, and the recovery file names the cards."""
    to_workspace(93)
    front, back = spawn('recovery-front'), spawn('recovery-back')
    ipc.focused((front, 'mark'), (back, 'card'))
    made = card_of(front)
    shows = made['current']
    other = next(a for a in (front, back) if a != shows)
    recovery = library.with_suffix('.upgrade.json')
    recovery.write_text(json.dumps({'instance': env['HYPRLAND_INSTANCE_SIGNATURE'], 'pairs': [],
                                    'cards': [card_restore.describe(made)]}))
    ipc.call('plugin', 'unload', str(library))
    # Without the core a focus turns the native group to that app.
    give_keyboard(other)
    rest(other)
    at = pointer()
    out = install()
    assert 'Keeping 1 open card(s)' in out and not recovery.exists(), out
    time.sleep(.3)
    after = card_of(front)
    assert (after['active'], after['current'], active(), pointer()) == (made['active'], shows, shows, at), (made, after, active(), at, pointer())
    assert [ipc.windows()[a]['acceptsInput'] for a in (shows, other)] == [True, False]


try:
    assert not ipc.data('-j', 'plugin', 'list'), 'Use a fresh nested session without a demo flag'
    # They stay on the session's first workspace, out of the layout this suite measures.
    session_windows(env)
    # Mirror a typical Omarchy desktop: 4K at 1.5x, focus following the mouse,
    # dwindle's smart and preserved splits, under which a dissolved card's tiles
    # reflow, and the values of the pilot desktop's options that decide what a
    # visit to a workspace does to the pointer and to a special workspace.
    names = {m['name'] for m in ipc.data('-j', 'monitors')}
    first = next(iter(names))
    ipc.call('output', 'create', 'headless')
    output = next(m['name'] for m in ipc.data('-j', 'monitors') if m['name'] not in names)
    settings = original + f'''
hl.monitor({{output="{output}",mode="3840x2160@60",position="2000x0",scale=1.5}})
''' + ''.join(f'hl.workspace_rule({{workspace="{n}",monitor="{output}"}})\n' for n in (90, 91, 92, 93, 94, 95, 97, 98)) + f'''
hl.config({{animations={{enabled=false}},general={{gaps_in=14,gaps_out=24}},input={{follow_mouse=1}},
    dwindle={{smart_split=true,preserve_split=true,force_split=2}},cursor={{warp_on_change_workspace=1}},
    binds={{hide_special_on_workspace_change=true}}}})
'''
    with_options()
    assert ipc.data('-j', 'getoption', 'cursor:warp_on_change_workspace')['int'] == 1
    assert ipc.data('-j', 'getoption', 'binds:hide_special_on_workspace_change')['bool'] is True
    ipc.call('dispatch', f'hl.dsp.focus({{monitor="{output}"}})')
    out = install()
    assert 'hyprflip' in {p['name'] for p in ipc.data('-j', 'plugin', 'list')}, out
    ipc.call('eval', 'hl.config({plugin={hyprflip={duration_ms=0,notifications=false}}})')
    passed('a fresh install loads the plugin from the disposable home')
    moves = Moves()
    os.environ.update({k: v for k, v in env.items() if k in ('HYPRLAND_INSTANCE_SIGNATURE', 'XDG_RUNTIME_DIR', 'WAYLAND_DISPLAY')})
    import card_restore

    check('with the keyboard on either app of a two-app face, an update with nothing to correct keeps it there', a_card_alone)
    session_front = next(a for a, window in ipc.windows().items() if window['class'] == 'hyprflip-front')
    for on_app, which in ((0, 'first'), (1, 'second')):
        check(f'with the keyboard on the {which} app of a two-app face, an update that corrects another card on that workspace '
              'keeps it there, with the pointer and the monitors', lambda: another_card_corrected_beside_it(on_app))
        check(f'with the keyboard on the {which} app of a two-app face and the pointer over the other monitor, an update that corrects '
              'another card on that workspace keeps it there, and changes only which monitor has the focus',
              lambda: another_card_corrected_beside_it(on_app, session_front))
    for apps in ((2, 2), (2, 3), (3, 3)):
        for turned in (False, True):
            check(f'two tiled cards of {apps[0]} and {apps[1]} apps alone on a workspace, {"turned to the other split" if turned else "as they fell"}, '
                  'stay in their tiles through three updates', lambda: two_cards_alone(90, f'pair{apps[0]}{apps[1]}', apps, turned))
    mark = len(processes)
    beside_another_monitor(first)
    clear(mark)
    check('a recovery run after a crash keeps the saved side, and a keyboard left on the other side does not turn the card', a_recovery_run)
    assert not open_cards(), open_cards()
    to_monitor(output)

    # A card another program parked out of sight. It is built on a workspace
    # of its own, so workspace 95's layout is what it would be without it.
    ipc.call('dispatch', 'hl.dsp.focus({workspace=96})')
    parked = [spawn('parked-front'), spawn('parked-back')]
    ipc.focused((parked[0], 'mark'), (parked[1], 'card'))
    hidden = next(card['id'] for card in ipc.status()['containers'] if parked[0] in sum(card['faces'], []))
    ipc.action(f'card {hidden} workspace special:park silent')

    ipc.call('dispatch', 'hl.dsp.focus({workspace=95})')
    # A neighbouring tile, so the card's place in the layout matters.
    neighbor = spawn('neighbor')
    a, b, c = spawn('front'), spawn('back'), spawn('notes')
    ipc.focused((a, 'mark'), (b, 'card')); ipc.focused((c, 'mark'), (b, 'attach horizontal'))
    ipc.focus(b)
    ipc.action(f'arrange horizontal {b}:0.7 {c}:0.3')
    d, e = spawn('float-front'), spawn('float-back')
    for x in (d, e): ipc.call('dispatch', f'hl.dsp.window.float({{window="address:{x}",action="enable"}})')
    ipc.focused((d, 'mark'), (e, 'card'))
    ipc.call('eval', f'hl.plugin.hyprflip.card_place("{d}", 300, 150, 700, 500)')
    ipc.focus(d); ipc.action('unfold')
    time.sleep(.3)
    cards = ipc.status()['containers']
    assert [sorted(sum(card['faces'], [])) for card in cards if card['workspace']['special']] == [sorted(parked)], cards
    assert len(open_cards()) == 2 and any(s['floating'] and s['unfolded'] for s, _ in open_cards().values()), cards

    # Positive control: here a plain focus puts the pointer in the middle of the
    # card, so a pointer left resting below means that nothing warped it.
    current = next(c for c in ipc.status()['containers'] if not c['floating'] and not c['workspace']['special'])['current']
    ipc.focus(current)
    x, y, width, height = tile(current)
    centre = pointer()
    assert abs(centre[0] - (x + width / 2)) <= 1 and abs(centre[1] - (y + height / 2)) <= 1, (centre, tile(current))

    # With smart_split, re-inserted tiles split whatever is under the cursor.
    rest(neighbor)
    ipc.call('dispatch', w.Unattended.focus_command(neighbor))
    wait(lambda: active() == neighbor)
    out = update(neighbor)
    passed('an update keeps a tiled 70/30 card beside its neighbour and an unfolded floating card exactly as they were, '
           'and leaves the keyboard and the pointer where they were')

    # The update rebuilt only those two: the parked card's apps stay where it
    # was, as separate windows, for the program that parked it to rebuild.
    assert 'Leaving 1 hidden card(s) as separate windows; the program that parked them rebuilds them.' in out, out
    assert 'Could not keep a card' not in out, out
    windows = ipc.windows()
    for address in parked:
        window = windows[address]
        assert window['workspace']['name'] == 'special:park' and not window['grouped'] and window['acceptsInput'], (window['workspace'], window['grouped'], window['acceptsInput'])
    passed('an update leaves a card parked on special:park as separate windows there and says how many')

    # A plain restore would give the last card rebuilt, the floating one, the
    # keyboard and show its workspace. With the keyboard on the other card's app
    # it stays there, on that card's shown side.
    ipc.call('dispatch', w.Unattended.focus_command(current))
    wait(lambda: active() == current)
    rest(neighbor)
    update(current)
    passed('an update with the keyboard on a card leaves it on that card')

    # From another workspace, no monitor comes to show the cards' workspace.
    ipc.call('dispatch', 'hl.dsp.focus({workspace=97})')
    elsewhere = spawn('elsewhere')
    wait(lambda: active() == elsewhere)
    rest(elsewhere)
    update(elsewhere)
    ipc.call('dispatch', 'hl.dsp.focus({workspace=95})')
    passed('an update from another workspace stays on that workspace, with the keyboard and the pointer')

    # Dwindle can reflow a workspace while a tiled card is briefly separate
    # tiles. Displace the card deliberately; the installer's correction must
    # put it back in its saved tile, and leave the keyboard and the pointer
    # where they were. The pointer rests off-centre over the neighbour, with
    # the keyboard first there, then on the card. Focus follows the mouse, as
    # on the desktop the pointer findings were measured on (only real pointer
    # motion moves the keyboard then, not a warp).
    assert ipc.data('-j', 'getoption', 'input:follow_mouse')['int'] == 1
    tiled = next(c for c in ipc.status()['containers'] if not c['floating'])
    line, saved, described = card_restore.describe(tiled), tuple(tiled['box']), shape(tiled)
    box = lambda: tuple(next(c for c in ipc.status()['containers'] if not c['floating'])['box'])

    def displace():
        # togglesplit and swapsplit act on the focused window.
        if active() != current:
            ipc.call('dispatch', w.Unattended.focus_command(current))
            wait(lambda: active() == current)
        for message in ('togglesplit', 'swapsplit'):
            ipc.call('dispatch', f'hl.dsp.layout("{message}")')
        displaced = box()
        assert sum(abs(p - q) for p, q in zip(displaced, saved)) > 50, (saved, displaced)
        return displaced

    for keyboard in (neighbor, current):
        displaced = displace()
        point = rest(neighbor)
        # Over the neighbour's tile and neither card.
        assert not any(c['box'][0] <= point[0] < c['box'][0] + c['box'][2] and c['box'][1] <= point[1] < c['box'][1] + c['box'][3]
                       for c in ipc.status()['containers']), (point, ipc.status()['containers'])
        if active() != keyboard:
            ipc.call('dispatch', w.Unattended.focus_command(keyboard))
            wait(lambda: active() == keyboard)
        assert pointer() == point, (point, pointer())
        card_restore.settle(line)
        settled, after = box(), pointer()
        print('pointer', point, after, 'keyboard on the', 'card' if keyboard == current else 'neighbour', flush=True)
        assert all(abs(p - q) <= 4 for p, q in zip(settled, saved)), (saved, displaced, settled)
        assert shape(next(c for c in ipc.status()['containers'] if not c['floating'])) == described
        assert after == point and active() == keyboard, (point, after, keyboard, active())
    passed('a tiled card displaced by a layout reflow is returned to its saved tile, and the keyboard and the pointer '
           'stay where they were')

    # For a window it will not focus, Hyprland answers ok and leaves the keyboard
    # where it is. The steps would then rearrange the tile that kept it.
    displaced = displace()
    ipc.call('dispatch', f'hl.dsp.window.set_prop({{window="address:{current}",prop="no_focus",value="1"}})')
    ipc.call('dispatch', w.Unattended.focus_command(neighbor))
    wait(lambda: active() == neighbor)
    point, beside = rest(neighbor), tile(neighbor)
    try:
        card_restore.settle(line)
    except RuntimeError as error:
        assert 'did not take the keyboard' in str(error), error
    else:
        raise AssertionError('settle went on without the keyboard')
    assert (box(), tile(neighbor), pointer(), active()) == (displaced, beside, point, neighbor), (displaced, box(), beside, tile(neighbor))
    assert shape(next(c for c in ipc.status()['containers'] if not c['floating'])) == described
    passed('a card that does not take the keyboard stays where it is, and no other tile moves')

    ipc.call('plugin', 'unload', str(library))
    assert 'hyprflip' not in {p['name'] for p in ipc.data('-j', 'plugin', 'list')}
    passed('the disposable install unloads cleanly')
    if failed:
        raise SystemExit(f'{len(failed)} of {len(failed) + len(checks)} checks failed')
finally:
    for process in processes:
        if process.poll() is None: process.terminate()
    try:
        if any(p['name'] == 'hyprflip' for p in ipc.data('-j', 'plugin', 'list')):
            ipc.call('plugin', 'unload', str(library))
    except Exception: pass
    try: config.write_text(original); ipc.call('reload')
    except Exception: pass
    try:
        if output: ipc.call('output', 'remove', output)
    except Exception: pass
    (root / 'install-cards-results.json').write_text(json.dumps(checks, indent=2))
