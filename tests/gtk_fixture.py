#!/usr/bin/env python3
"""Disposable GTK window for native/XWayland, popup and modal tests."""
import sys
from pathlib import Path
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

name = sys.argv[1]
commands = Path(sys.argv[2])
GLib.set_prgname(name)
Gtk.init()
window = Gtk.Window(title=name)
window.set_default_size(500, 400)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
box.set_margin_top(30); box.set_margin_start(30)
box.append(Gtk.Label(label=name + "\n\nLEFT                           RIGHT"))
popover = Gtk.Popover()
popover.set_child(Gtk.Label(label="Test popup menu"))
button = Gtk.MenuButton(label="Menu", popover=popover)
box.append(button)
window.set_child(box)
loop = GLib.MainLoop()
window.connect("close-request", lambda *_: loop.quit())
last = ""
dialog = None
def poll():
    global last, dialog
    command = commands.read_text().strip() if commands.exists() else ""
    if command == last:
        return True
    last = command
    if command == "popup": popover.popup()
    elif command == "dismiss":
        popover.popdown()
        if dialog: dialog.close(); dialog = None
    elif command == "modal":
        dialog = Gtk.Window(title="Hyprflip modal", transient_for=window, modal=True)
        dialog.set_child(Gtk.Label(label="A real modal child"))
        dialog.set_default_size(300, 140); dialog.present()
    elif command == "close": window.close()
    elif command.startswith("minimum "):
        width, height = map(int, command.split()[1:])
        # Constrain content before presenting the toplevel in minimum-size
        # tests, so the initial Wayland commit advertises the requested limit.
        box.set_size_request(width, height)
    return True
poll()
window.present()
GLib.timeout_add(50, poll)
loop.run()
