#!/usr/bin/env python3
# Notification center icon for polybar (custom/script, tail = true).
# - dunst publishes paused / displayedLength / historyLength / waitingLength on
#   org.dunstproject.cmd0 and emits PropertiesChanged for each, so this script just listens
#   (no polling of dunstctl).
#   paused -> bell-off, any notification (shown, in history or waiting) -> bell-badge, else bell.
# - Clicking the icon opens notif-center.py (rofi), see module/notif in miniblocks/config.ini.

import os
import sys

from gi.repository import Gio, GLib

DUNST = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"
IFACE = "org.dunstproject.cmd0"
POLL_SEC = 30         # safety net only

ICON_BELL = "\U000F009A"        # nf-md-bell
ICON_BADGE = "\U000F116B"       # nf-md-bell_badge
ICON_OFF = "\U000F13E7"         # nf-md-bell_off_outline (방해 금지)
# polybar font slot for the icon (%{T<n>}): hack bar = 2 (default), miniblocks passes env-NOTIF_FONT
FONT = os.environ.get("NOTIF_FONT", "2")

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
last = None
PARENT = os.getppid()


def output(text):
    global last
    if text != last:
        last = text
        try:
            print(f"%{{T{FONT}}}{text}%{{T-}}", flush=True)
        except BrokenPipeError:
            os._exit(0)   # polybar is gone


def refresh(*_):
    # polybar quit (logout etc.) -> reparented to init; don't linger as an orphan
    if os.getppid() != PARENT:
        os._exit(0)
    try:
        # NO_AUTO_START: dunst is D-Bus activated; don't start it just to draw the icon
        (props,) = bus.call_sync(DUNST, PATH, "org.freedesktop.DBus.Properties", "GetAll",
                                 GLib.Variant("(s)", (IFACE,)), None,
                                 Gio.DBusCallFlags.NO_AUTO_START, 1000, None).unpack()
    except GLib.Error:
        output(ICON_BELL)
        return True
    count = sum(props.get(k, 0) for k in ("displayedLength", "historyLength", "waitingLength"))
    if props.get("paused"):
        output(ICON_OFF)
    else:
        output(ICON_BADGE if count else ICON_BELL)
    return True


bus.signal_subscribe(None, "org.freedesktop.DBus.Properties", "PropertiesChanged", PATH, IFACE,
                     Gio.DBusSignalFlags.NONE, refresh)
# history-rm / history-clear also emit their own signals
bus.signal_subscribe(None, IFACE, None, PATH, None, Gio.DBusSignalFlags.NONE, refresh)
Gio.bus_watch_name_on_connection(bus, DUNST, Gio.BusNameWatcherFlags.NONE,
                                 lambda *_: refresh(), lambda *_: refresh())
GLib.timeout_add_seconds(POLL_SEC, refresh)

refresh()
try:
    GLib.MainLoop().run()
except KeyboardInterrupt:
    sys.exit(0)
