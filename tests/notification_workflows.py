#!/usr/bin/env python3
"""Test notify-send progress against a private freedesktop notification service."""
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

if sys.argv[1:] != ['--private-bus']:
    raise SystemExit(subprocess.run(['dbus-run-session', '--', sys.executable, __file__, '--private-bus']).returncode)

from gi.repository import Gio, GLib
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import workflow as w

interface = 'org.freedesktop.Notifications'
path = '/org/freedesktop/Notifications'
connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
connection.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                     'RequestName', GLib.Variant('(su)', (interface, 0)), None, Gio.DBusCallFlags.NONE, 3000, None)
xml = '''<node><interface name="org.freedesktop.Notifications">
<method name="GetCapabilities"><arg type="as" direction="out"/></method>
<method name="GetServerInformation"><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/><arg type="s" direction="out"/></method>
<method name="Notify"><arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/><arg type="a{sv}" direction="in"/><arg type="i" direction="in"/><arg type="u" direction="out"/></method>
<method name="CloseNotification"><arg type="u" direction="in"/></method>
<signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
<signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
</interface></node>'''
received, closed = [], []


def call(conn, sender, object_path, iface, method, parameters, invocation):
    if method == 'GetCapabilities': invocation.return_value(GLib.Variant('(as)', (['actions', 'body'],)))
    elif method == 'GetServerInformation': invocation.return_value(GLib.Variant('(ssss)', ('Fixture', 'Hyprflip tests', '1', '1.2')))
    elif method == 'Notify':
        received.append(parameters.unpack())
        invocation.return_value(GLib.Variant('(u)', (len(received),)))
    elif method == 'CloseNotification':
        identifier = parameters.unpack()[0]
        closed.append(identifier)
        invocation.return_value(None)
        conn.emit_signal(None, path, interface, 'NotificationClosed', GLib.Variant('(uu)', (identifier, 3)))


registration = connection.register_object(path, Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0], call, None, None)
loop = GLib.MainLoop()
thread = threading.Thread(target=loop.run, daemon=True)
thread.start()


def wait(predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.025)
    raise AssertionError('Notification protocol timed out')


try:
    with w.Opening('Comms', ['Mail', 'Chat'], dict(os.environ)) as progress:
        wait(lambda: len(received) == 1)
        wait(lambda: progress.answer.read_text().splitlines() == ['1'])
        assert progress.process.poll() is None
    assert closed == [1]
    print('PASS notification ID is flushed before completion and only that notification is closed')
    with w.Opening('Project', ['Editor'], dict(os.environ)) as progress:
        wait(lambda: len(received) == 2)
        connection.emit_signal(None, path, interface, 'ActionInvoked', GLib.Variant('(us)', (2, 'default')))
        wait(lambda: 'default' in progress.answer.read_text().splitlines())
        try: progress.check()
        except w.Cancelled: pass
        else: raise AssertionError('Cancel action was ignored')
    assert 2 in closed and set(closed) == {1, 2}
    print('PASS standard notification action cancels saved-card opening')
finally:
    loop.quit()
    thread.join(timeout=2)
    connection.unregister_object(registration)
