#!/usr/bin/env python3
# One Python process for three miniblocks modules (exec of [module/traywidth]):
#   stdout       -> traywidth: 1px mark, shapes the tray bar to its content
#   FIFO notif   -> notif: dunst bell icon (D-Bus signals via libdbus)
#   FIFO music   -> music: focused window title, marquee when it overflows
# FIFOs live in $XDG_RUNTIME_DIR/barsd; the modules read them with barsd-read.sh.
# A reader opening its FIFO (inotify IN_OPEN) gets the current line again.
#
# Env (set on [module/traywidth]):
#   TRAYWIDTH_LEFT, TRAYWIDTH_MARK, TRAYWIDTH_ANIM
#   NOTIF_FONT
#   MARQUEE_VIEW_PX, MARQUEE_SPEED, MARQUEE_FPS, MARQUEE_PAUSE, MARQUEE_FADE, MARQUEE_EDGE_PX,
#   MARQUEE_DIRECTION, MARQUEE_FG, MARQUEE_OFFLINE, MARQUEE_OFFLINE_FONT, MARQUEE_DPI, MARQUEE_FONT_0..9

import bisect
import ctypes as C
import errno
import math
import os
import re
import select
import signal
import stat
import struct
import subprocess
import sys
import time
import unicodedata

ENV = os.environ
RUN = os.path.join(ENV.get("XDG_RUNTIME_DIR") or "/tmp", "barsd")
PARENT = os.getppid()
SAFETY = 30.0        # max sleep: parent check + notif safety refresh
LIBC = C.CDLL(None, use_errno=True)
vp, ul = C.c_void_p, C.c_ulong


# ---------------------------------------------------------------- outputs

class Fifo:
    """One FIFO output. Writes are dropped while nobody reads; reconnect on IN_OPEN."""

    def __init__(self, name):
        self.name = name
        self.path = os.path.join(RUN, name)
        self.fd = None
        self.line = None
        try:
            if not stat.S_ISFIFO(os.stat(self.path).st_mode):
                os.unlink(self.path)
                os.mkfifo(self.path)
        except FileNotFoundError:
            try:
                os.mkfifo(self.path)
            except FileExistsError:
                pass

    def connect(self):
        if self.fd is None:
            try:
                self.fd = os.open(self.path, os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            except OSError:
                return  # no reader yet
        self._write()

    def send(self, line):
        self.line = line
        if self.fd is not None:
            self._write()

    def _write(self):
        if self.line is None:
            return
        try:
            os.write(self.fd, (self.line + "\n").encode())
        except BlockingIOError:
            pass  # reader stalled: drop this line
        except OSError:  # EPIPE: reader gone
            os.close(self.fd)
            self.fd = None


class Watch:
    """inotify IN_OPEN on RUN: a module (re)opened its FIFO."""

    IN_OPEN = 0x20

    def __init__(self, fifos):
        self.fifos = {f.name: f for f in fifos}
        self.fd = LIBC.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0 or LIBC.inotify_add_watch(self.fd, RUN.encode(), self.IN_OPEN) < 0:
            raise OSError(C.get_errno(), "inotify")

    def fds(self):
        return [self.fd]

    def timeout(self, now):
        return None

    def handle(self, ready):
        if self.fd not in ready:
            return
        try:
            buf = os.read(self.fd, 65536)
        except BlockingIOError:
            return
        names, i = set(), 0
        while i + 16 <= len(buf):
            _, _, _, n = struct.unpack_from("iIII", buf, i)
            names.add(buf[i + 16:i + 16 + n].rstrip(b"\0").decode(errors="replace"))
            i += 16 + n
        for name in names:
            if name in self.fifos:
                self.fifos[name].connect()

    def tick(self, now):
        pass


# ---------------------------------------------------------------- traywidth
# polybar 3.7 can't resize a bar at runtime: the tray bar keeps its config width and
# an X Shape cuts its left side at the mark (first module) - TRAYWIDTH_LEFT px.
# Wakes only on XDamage of the bar; new widths are probed by briefly opening the full bar.

class XImage(C.Structure):
    _fields_ = [("width", C.c_int), ("height", C.c_int), ("xoffset", C.c_int), ("format", C.c_int),
                ("data", C.POINTER(C.c_ubyte)), ("byte_order", C.c_int), ("bitmap_unit", C.c_int),
                ("bitmap_bit_order", C.c_int), ("bitmap_pad", C.c_int), ("depth", C.c_int),
                ("bytes_per_line", C.c_int), ("bits_per_pixel", C.c_int)]


class XRectangle(C.Structure):
    _fields_ = [("x", C.c_short), ("y", C.c_short), ("width", C.c_ushort), ("height", C.c_ushort)]


class XEvent(C.Union):
    _fields_ = [("type", C.c_int), ("pad", C.c_long * 24)]


# X errors (bar window gone mid-request) would kill the process: ignore, DestroyNotify ends us
X_ERROR_HANDLER = C.CFUNCTYPE(C.c_int, vp, vp)(lambda d, e: 0)


def ppid_of(pid):
    try:
        return int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return None


class TrayWidth:
    DESTROY_NOTIFY = 17
    STRUCTURE_NOTIFY_MASK = 1 << 17
    DAMAGE_REPORT_NON_EMPTY = 3
    Z_PIXMAP = 2
    SHAPE_BOUNDING, SHAPE_INPUT, SHAPE_SET, UNSORTED = 0, 2, 0, 0
    CARDINAL = 6
    SETTLE = 0.004       # wait for the redraw to finish
    FRAME = 1 / 120

    def __init__(self):
        self.LEFT = int(ENV.get("TRAYWIDTH_LEFT", "15"))
        self.ANIM = float(ENV.get("TRAYWIDTH_ANIM", "0.15"))
        debug = ENV.get("TRAYWIDTH_DEBUG")
        self.dbg = open(debug, "a") if debug else None

        X = self.X = C.CDLL("libX11.so.6")
        XD = self.XD = C.CDLL("libXdamage.so.1")
        XE = self.XE = C.CDLL("libXext.so.6")
        X.XOpenDisplay.restype = vp; X.XOpenDisplay.argtypes = [C.c_char_p]
        X.XDefaultRootWindow.restype = ul; X.XDefaultRootWindow.argtypes = [vp]
        X.XInternAtom.restype = ul; X.XInternAtom.argtypes = [vp, C.c_char_p, C.c_int]
        X.XQueryTree.argtypes = [vp, ul, C.POINTER(ul), C.POINTER(ul), C.POINTER(C.POINTER(ul)), C.POINTER(C.c_uint)]
        X.XFetchName.argtypes = [vp, ul, C.POINTER(C.c_char_p)]
        X.XGetWindowProperty.argtypes = [vp, ul, ul, C.c_long, C.c_long, C.c_int, ul, C.POINTER(ul),
                                         C.POINTER(C.c_int), C.POINTER(ul), C.POINTER(ul), C.POINTER(C.POINTER(C.c_ubyte))]
        X.XFree.argtypes = [vp]
        X.XGetGeometry.argtypes = [vp, ul, C.POINTER(ul), C.POINTER(C.c_int), C.POINTER(C.c_int),
                                   C.POINTER(C.c_uint), C.POINTER(C.c_uint), C.POINTER(C.c_uint), C.POINTER(C.c_uint)]
        X.XSelectInput.argtypes = [vp, ul, C.c_long]
        X.XGetImage.restype = C.POINTER(XImage)
        X.XGetImage.argtypes = [vp, ul, C.c_int, C.c_int, C.c_uint, C.c_uint, ul, C.c_int]
        X.XPending.argtypes = [vp]; X.XNextEvent.argtypes = [vp, C.POINTER(XEvent)]
        X.XConnectionNumber.argtypes = [vp]; X.XFlush.argtypes = [vp]
        X.XSetErrorHandler.argtypes = [vp]
        XD.XDamageQueryExtension.argtypes = [vp, C.POINTER(C.c_int), C.POINTER(C.c_int)]
        XD.XDamageCreate.restype = ul; XD.XDamageCreate.argtypes = [vp, ul, C.c_int]
        XD.XDamageSubtract.argtypes = [vp, ul, ul, ul]
        XE.XShapeCombineRectangles.argtypes = [vp, ul, C.c_int, C.c_int, C.c_int, C.POINTER(XRectangle),
                                               C.c_int, C.c_int, C.c_int]
        X.XSetErrorHandler(C.cast(X_ERROR_HANDLER, vp))

        self.dpy = X.XOpenDisplay(None)
        if not self.dpy:
            raise RuntimeError("traywidth: no display")
        ev_base, err_base = C.c_int(), C.c_int()
        if not XD.XDamageQueryExtension(self.dpy, C.byref(ev_base), C.byref(err_base)):
            raise RuntimeError("traywidth: no XDamage")
        self.DAMAGE_NOTIFY = ev_base.value
        self.root = X.XDefaultRootWindow(self.dpy)
        self.NET_WM_PID = X.XInternAtom(self.dpy, b"_NET_WM_PID", 0)
        self.xfd = X.XConnectionNumber(self.dpy)
        self.ev = XEvent()
        # polybar may run us through sh -c: accept its parent too
        self.owners = {PARENT, ppid_of(PARENT)} - {None, 0, 1}

        self.bar = None
        self.tries = 0
        self.next_try = 0.0
        self.W = self.H = 0
        self.left = 0            # current left edge of the visible area (0 = full)
        self.target = 0
        self.anim = None         # (start time, from, to)
        self.probe_from = None   # edge to return to after probing an unknown width
        self.first = True
        self.seen = set()        # edges fitted before (per mute/wifi state)
        self.pending_fit = None
        self.next_frame = None

    def log(self, msg):
        if self.dbg:
            print(f"{time.monotonic():.3f} {msg}", file=self.dbg, flush=True)

    def wm_pid(self, win):
        X = self.X
        t, f, n, a = ul(), C.c_int(), ul(), ul()
        p = C.POINTER(C.c_ubyte)()
        if X.XGetWindowProperty(self.dpy, win, self.NET_WM_PID, 0, 1, 0, self.CARDINAL, C.byref(t), C.byref(f),
                                C.byref(n), C.byref(a), C.byref(p)) != 0 or not p:
            return None
        pid = C.cast(p, C.POINTER(C.c_uint32))[0] if n.value else None
        X.XFree(p)
        return pid

    def find_bar(self):
        X = self.X
        r, par, n = ul(), ul(), C.c_uint()
        kids = C.POINTER(ul)()
        if not X.XQueryTree(self.dpy, self.root, C.byref(r), C.byref(par), C.byref(kids), C.byref(n)):
            return None
        found = None
        for i in range(n.value):
            w = kids[i]
            name = C.c_char_p()
            if X.XFetchName(self.dpy, w, C.byref(name)) and name.value:
                ok = name.value.startswith(b"polybar-")
                X.XFree(C.cast(name, vp))
                if ok and self.wm_pid(w) in self.owners:
                    found = w
                    break
        if kids:
            X.XFree(kids)
        return found

    def attach(self, bar):
        X = self.X
        r, x, y, w, h, b, d = ul(), C.c_int(), C.c_int(), C.c_uint(), C.c_uint(), C.c_uint(), C.c_uint()
        if not X.XGetGeometry(self.dpy, bar, C.byref(r), C.byref(x), C.byref(y), C.byref(w), C.byref(h),
                              C.byref(b), C.byref(d)):
            return False
        self.bar, self.W, self.H = bar, w.value, h.value
        self.damage = self.XD.XDamageCreate(self.dpy, bar, self.DAMAGE_REPORT_NON_EMPTY)
        X.XSelectInput(self.dpy, bar, self.STRUCTURE_NOTIFY_MASK)
        X.XFlush(self.dpy)
        self.pending_fit = time.monotonic()
        return True

    def set_left(self, x):
        self.log(f"set_left {self.left} -> {x}")
        self.left = max(0, min(self.W - 1, x))
        rect = XRectangle(self.left, 0, self.W - self.left, self.H)
        for kind in (self.SHAPE_BOUNDING, self.SHAPE_INPUT):
            self.XE.XShapeCombineRectangles(self.dpy, self.bar, kind, 0, 0, C.byref(rect), 1,
                                            self.SHAPE_SET, self.UNSORTED)
        self.X.XFlush(self.dpy)

    def find_mark(self):
        """Leftmost column in the visible area whose top pixel differs from the background
        (= top-right pixel), -1 if none. The cut-off part may hold stale pixels, so skip it."""
        X = self.X
        img = X.XGetImage(self.dpy, self.bar, self.left, 0, self.W - self.left, 1, 0xFFFFFFFF, self.Z_PIXMAP)
        if not img:
            return None
        im = img.contents
        n = im.width
        raw = C.string_at(im.data, 4 * n)
        X.XFree(im.data)
        X.XFree(img)
        bg = raw[-4:]
        for i in range(n):
            if raw[4 * i: 4 * i + 4] != bg:
                return self.left + i
        return -1

    def animate_to(self, x, start=None):
        """Slide the edge to x over ANIM s (ease-out), from start (default: current edge)."""
        self.target = x
        s0 = self.left if start is None else start
        if self.ANIM <= 0 or s0 == x:
            self.anim = None
            if self.left != x:
                self.set_left(x)
            return
        self.anim = (time.monotonic(), s0, x)

    def step(self):
        """One animation frame; False when done."""
        t0, a, b = self.anim
        t = min(1.0, (time.monotonic() - t0) / self.ANIM)
        e = 1 - (1 - t) ** 3
        x = round(a + (b - a) * e)
        if x != self.left:
            self.set_left(x)
        if t >= 1.0:
            self.anim = None
            return False
        return True

    def fit(self):
        """Measure and move the edge; returns the next forced re-measure time or None."""
        m = self.find_mark()
        self.log(f"fit left={self.left} target={self.target} mark={m}")
        if m is None:
            return None
        if m < 0:
            if self.anim and self.target < self.left:
                return None   # still unfolding: re-measure when done
            if self.left == 0:
                return None   # mark not drawn yet
            # mark is in the cut-off part = content grew: use the next wider known edge
            known = [x for x in self.seen if x < self.left]
            if known:
                self.animate_to(max(known))
                return None
            # unknown width: open fully, measure on redraw (or in 0.1 s), slide from the old edge
            self.probe_from = self.left if self.probe_from is None else self.probe_from
            self.anim = None
            self.set_left(0)
            return time.monotonic() + 0.1
        new = max(0, m - self.LEFT)
        if len(self.seen) < 64:
            self.seen.add(new)
        if self.probe_from is not None:
            start, self.probe_from = self.probe_from, None
            self.set_left(start)
            self.animate_to(new, start)
        elif self.first:
            self.first = False
            self.animate_to(new, new)
            if self.left != new:
                self.set_left(new)
        elif new != self.target:
            self.animate_to(new)
        return None

    def fds(self):
        return [self.xfd]

    def timeout(self, now):
        if self.bar is None:
            return max(0.0, self.next_try - now)
        if self.X.XPending(self.dpy):
            return 0.0
        due = [t for t in (self.pending_fit, self.next_frame) if t is not None]
        return max(0.0, min(due) - now) if due else None

    def handle(self, ready):
        X, ev = self.X, self.ev
        while X.XPending(self.dpy):
            X.XNextEvent(self.dpy, C.byref(ev))
            if self.bar is None:
                continue
            if ev.type == self.DAMAGE_NOTIFY:
                self.XD.XDamageSubtract(self.dpy, self.damage, 0, 0)
                soon = time.monotonic() + self.SETTLE
                if self.pending_fit is None or self.pending_fit > soon:
                    self.pending_fit = soon
            elif ev.type == self.DESTROY_NOTIFY:
                sys.exit(0)   # bar is going away: polybar restarts us

    def tick(self, now):
        if self.bar is None:
            if now < self.next_try:
                return
            bar = self.find_bar()   # the bar window may not exist yet right after start
            if bar and self.attach(bar):
                return
            self.tries += 1
            self.next_try = now + 0.05 if self.tries < 200 else float("inf")
            if self.tries == 200:
                print("barsd: tray bar window not found", file=sys.stderr)
            return
        if self.pending_fit is not None and now >= self.pending_fit:
            self.pending_fit = self.fit()
        if self.anim:
            if self.next_frame is None or now >= self.next_frame:
                if self.step():
                    self.next_frame = now + self.FRAME
                else:
                    self.next_frame = None
                    self.pending_fit = time.monotonic()   # re-check after unfolding
        else:
            self.next_frame = None


# ---------------------------------------------------------------- notif
# dunst publishes paused / displayedLength / historyLength / waitingLength on
# org.dunstproject.cmd0 and emits PropertiesChanged: paused -> bell-off,
# any notification (shown, history, waiting) -> bell-badge, else bell.

class Notif:
    DEST = b"org.freedesktop.Notifications"
    PATH = b"/org/freedesktop/Notifications"
    IFACE = b"org.dunstproject.cmd0"
    MATCHES = (
        b"type='signal',path='/org/freedesktop/Notifications',interface='org.freedesktop.DBus.Properties',"
        b"member='PropertiesChanged',arg0='org.dunstproject.cmd0'",
        b"type='signal',path='/org/freedesktop/Notifications',interface='org.dunstproject.cmd0'",
        b"type='signal',sender='org.freedesktop.DBus',interface='org.freedesktop.DBus',"
        b"member='NameOwnerChanged',arg0='org.freedesktop.Notifications'",
    )
    ICON_BELL = "\U000F009A"      # nf-md-bell
    ICON_BADGE = "\U000F116B"     # nf-md-bell_badge
    ICON_OFF = "\U000F13E7"       # nf-md-bell_off_outline (do not disturb)
    WANT = {"paused", "displayedLength", "historyLength", "waitingLength"}

    def __init__(self, out):
        self.out = out
        self.font = ENV.get("NOTIF_FONT", "2")
        self.next_poll = 0.0
        self.fd = None
        self.conn = None
        d = self.d = C.CDLL("libdbus-1.so.3")
        d.dbus_error_init.argtypes = [vp]
        d.dbus_error_is_set.argtypes = [vp]
        d.dbus_error_free.argtypes = [vp]
        d.dbus_bus_get.restype = vp; d.dbus_bus_get.argtypes = [C.c_int, vp]
        d.dbus_connection_set_exit_on_disconnect.argtypes = [vp, C.c_uint]
        d.dbus_connection_get_is_connected.argtypes = [vp]
        d.dbus_bus_add_match.argtypes = [vp, C.c_char_p, vp]
        d.dbus_connection_flush.argtypes = [vp]
        d.dbus_connection_get_unix_fd.argtypes = [vp, C.POINTER(C.c_int)]
        d.dbus_connection_read_write.argtypes = [vp, C.c_int]
        d.dbus_connection_get_dispatch_status.argtypes = [vp]
        d.dbus_connection_pop_message.restype = vp; d.dbus_connection_pop_message.argtypes = [vp]
        d.dbus_message_unref.argtypes = [vp]
        d.dbus_message_new_method_call.restype = vp
        d.dbus_message_new_method_call.argtypes = [C.c_char_p] * 4
        d.dbus_message_set_auto_start.argtypes = [vp, C.c_uint]
        d.dbus_message_iter_init_append.argtypes = [vp, vp]
        d.dbus_message_iter_append_basic.argtypes = [vp, C.c_int, vp]
        d.dbus_connection_send_with_reply_and_block.restype = vp
        d.dbus_connection_send_with_reply_and_block.argtypes = [vp, vp, C.c_int, vp]
        d.dbus_message_iter_init.argtypes = [vp, vp]
        d.dbus_message_iter_recurse.argtypes = [vp, vp]
        d.dbus_message_iter_get_basic.argtypes = [vp, vp]
        d.dbus_message_iter_get_arg_type.argtypes = [vp]
        d.dbus_message_iter_next.argtypes = [vp]

        err = self.error()
        conn = d.dbus_bus_get(0, err)   # DBUS_BUS_SESSION
        if not conn:
            d.dbus_error_free(err)
            return
        d.dbus_connection_set_exit_on_disconnect(conn, 0)
        for rule in self.MATCHES:
            d.dbus_bus_add_match(conn, rule, None)
        d.dbus_connection_flush(conn)
        fd = C.c_int(-1)
        if d.dbus_connection_get_unix_fd(conn, C.byref(fd)):
            self.conn, self.fd = conn, fd.value

    def error(self):
        err = C.create_string_buffer(64)   # DBusError
        self.d.dbus_error_init(err)
        return err

    @staticmethod
    def it():
        return C.create_string_buffer(128)  # DBusMessageIter (72 bytes on x86_64)

    def get_all(self):
        """dunst's cmd0 properties, None if dunst isn't running (never auto-starts it)."""
        d = self.d
        msg = d.dbus_message_new_method_call(self.DEST, self.PATH, b"org.freedesktop.DBus.Properties", b"GetAll")
        if not msg:
            return None
        d.dbus_message_set_auto_start(msg, 0)
        it = self.it()
        d.dbus_message_iter_init_append(msg, it)
        s = C.c_char_p(self.IFACE)
        d.dbus_message_iter_append_basic(it, ord("s"), C.byref(s))
        err = self.error()
        reply = d.dbus_connection_send_with_reply_and_block(self.conn, msg, 1000, err)
        d.dbus_message_unref(msg)
        if not reply:
            d.dbus_error_free(err)
            return None
        props = {}
        top, arr = self.it(), self.it()
        if d.dbus_message_iter_init(reply, top) and d.dbus_message_iter_get_arg_type(top) == ord("a"):
            d.dbus_message_iter_recurse(top, arr)
            while d.dbus_message_iter_get_arg_type(arr) == ord("e"):
                ent, var = self.it(), self.it()
                d.dbus_message_iter_recurse(arr, ent)
                if d.dbus_message_iter_get_arg_type(ent) == ord("s"):
                    key = C.c_char_p()
                    d.dbus_message_iter_get_basic(ent, C.byref(key))
                    name = (key.value or b"").decode()
                    d.dbus_message_iter_next(ent)
                    if name in self.WANT and d.dbus_message_iter_get_arg_type(ent) == ord("v"):
                        d.dbus_message_iter_recurse(ent, var)
                        if d.dbus_message_iter_get_arg_type(var) in (ord("b"), ord("u"), ord("i")):
                            v = C.c_uint32()
                            d.dbus_message_iter_get_basic(var, C.byref(v))
                            props[name] = v.value
                d.dbus_message_iter_next(arr)
        d.dbus_message_unref(reply)
        return props

    def refresh(self):
        self.next_poll = time.monotonic() + SAFETY
        props = self.get_all() if self.conn else None
        if props is None:
            icon = self.ICON_BELL
        elif props.get("paused"):
            icon = self.ICON_OFF
        else:
            count = sum(props.get(k, 0) for k in ("displayedLength", "historyLength", "waitingLength"))
            icon = self.ICON_BADGE if count else self.ICON_BELL
        line = f"%{{T{self.font}}}{icon}%{{T-}}"
        if line != self.out.line:
            self.out.send(line)

    def drain(self):
        got = False
        while True:
            m = self.d.dbus_connection_pop_message(self.conn)
            if not m:
                return got
            self.d.dbus_message_unref(m)
            got = True

    def fds(self):
        return [self.fd] if self.fd is not None else []

    def timeout(self, now):
        if self.conn and self.d.dbus_connection_get_dispatch_status(self.conn) == 0:  # DATA_REMAINS
            return 0.0
        return max(0.0, self.next_poll - now)

    def handle(self, ready):
        if not self.conn:
            return
        if self.fd in ready:
            self.d.dbus_connection_read_write(self.conn, 0)
            if not self.d.dbus_connection_get_is_connected(self.conn):
                self.conn, self.fd = None, None
                self.refresh()
                return
        if self.drain():
            self.refresh()

    def tick(self, now):
        if now >= self.next_poll:
            self.refresh()


# ---------------------------------------------------------------- music (title marquee)
# Shows the focused window's _NET_WM_NAME (else WM_NAME) as-is, OFFLINE when no window.
# Fits in VIEW px -> static (polybar centers it); overflows -> smooth per-pixel scroll,
# faded edges, GAP between repeats, module width fixed at VIEW. Window switch fades out/in,
# a title change on the same window swaps in place. Widths follow polybar 3.7
# (fontconfig -> cairo, ceil(x_advance) of the first font that has the glyph).

VIEW = int(ENV.get("MARQUEE_VIEW_PX", 560))
SPEED = float(ENV.get("MARQUEE_SPEED", 30))         # px/s
FPS = float(ENV.get("MARQUEE_FPS", 30))
PAUSE = float(ENV.get("MARQUEE_PAUSE", 1.5))        # pause per loop, 0 = continuous
FADE = float(ENV.get("MARQUEE_FADE", 0.2))          # fade out / in on window switch, s each
EDGE = float(ENV.get("MARQUEE_EDGE_PX", 24))        # faded edge width while scrolling
DIRECTION = ENV.get("MARQUEE_DIRECTION", "left")
FG = ENV.get("MARQUEE_FG", "#c2c4c6")
OFFLINE = ENV.get("MARQUEE_OFFLINE", "  offline")
OFFLINE_FONT = ENV.get("MARQUEE_OFFLINE_FONT", "").strip()   # %{T<n>} for OFFLINE's first char
DPI = float(ENV.get("MARQUEE_DPI") or 96)
GAP = "     "
XENV = dict(ENV, LC_ALL="C")                        # xprop prints non-ASCII as \ooo (see decode)
FRAME = 1 / FPS


class Fonts:
    """polybar 3.7 cairo/font.hpp + context.hpp font selection and advance widths."""

    def __init__(self, specs, dpi):
        c = C
        fc = c.CDLL("libfontconfig.so.1")
        cr = c.CDLL("libcairo.so.2")
        ft = c.CDLL("libfreetype.so.6")

        class Matrix(c.Structure):
            _fields_ = [(n, c.c_double) for n in ("xx", "yx", "xy", "yy", "x0", "y0")]

        class Extents(c.Structure):
            _fields_ = [(n, c.c_double) for n in
                        ("x_bearing", "y_bearing", "width", "height", "x_advance", "y_advance")]

        fc.FcNameParse.restype = vp
        fc.FcNameParse.argtypes = [c.c_char_p]
        fc.FcDefaultSubstitute.argtypes = [vp]
        fc.FcConfigSubstitute.argtypes = [vp, vp, c.c_int]
        fc.FcFontMatch.restype = vp
        fc.FcFontMatch.argtypes = [vp, vp, c.POINTER(c.c_int)]
        fc.FcPatternDestroy.argtypes = [vp]
        fc.FcPatternGetDouble.argtypes = [vp, c.c_char_p, c.c_int, c.POINTER(c.c_double)]
        fc.FcPatternGetBool.argtypes = [vp, c.c_char_p, c.c_int, c.POINTER(c.c_int)]
        cr.cairo_matrix_init_scale.argtypes = [c.POINTER(Matrix), c.c_double, c.c_double]
        cr.cairo_matrix_init_identity.argtypes = [c.POINTER(Matrix)]
        cr.cairo_ft_font_face_create_for_pattern.restype = vp
        cr.cairo_ft_font_face_create_for_pattern.argtypes = [vp]
        cr.cairo_font_options_create.restype = vp
        cr.cairo_font_options_destroy.argtypes = [vp]
        cr.cairo_font_face_destroy.argtypes = [vp]
        cr.cairo_scaled_font_create.restype = vp
        cr.cairo_scaled_font_create.argtypes = [vp, c.POINTER(Matrix), c.POINTER(Matrix), vp]
        cr.cairo_scaled_font_status.argtypes = [vp]
        cr.cairo_scaled_font_text_extents.argtypes = [vp, c.c_char_p, c.POINTER(Extents)]
        cr.cairo_ft_scaled_font_lock_face.restype = vp
        cr.cairo_ft_scaled_font_lock_face.argtypes = [vp]
        cr.cairo_ft_scaled_font_unlock_face.argtypes = [vp]
        ft.FT_Get_Char_Index.restype = c.c_uint
        ft.FT_Get_Char_Index.argtypes = [vp, c.c_ulong]
        ft.FT_Select_Charmap.argtypes = [vp, c.c_int]

        self.cr, self.ft, self.Extents = cr, ft, Extents
        if not fc.FcInit():
            raise RuntimeError("FcInit")
        self.scaled = []
        for spec in specs:
            name, _, off = spec.rpartition(";")
            if not name or not off.strip().lstrip("-").replace(".", "").isdigit():
                name = spec  # no ";offset"
            pat = fc.FcNameParse(name.strip().encode())
            if not pat:
                continue
            fc.FcDefaultSubstitute(pat)
            fc.FcConfigSubstitute(None, pat, 0)  # FcMatchPattern
            res = c.c_int()
            match = fc.FcFontMatch(None, pat, c.byref(res))
            fc.FcPatternDestroy(pat)
            if not match:
                continue
            size = self.size(fc, match, dpi)
            fm, ctm = Matrix(), Matrix()
            cr.cairo_matrix_init_scale(c.byref(fm), size, size)
            cr.cairo_matrix_init_identity(c.byref(ctm))
            face = cr.cairo_ft_font_face_create_for_pattern(match)
            opts = cr.cairo_font_options_create()
            sf = cr.cairo_scaled_font_create(face, c.byref(fm), c.byref(ctm), opts)
            cr.cairo_font_options_destroy(opts)
            cr.cairo_font_face_destroy(face)
            if cr.cairo_scaled_font_status(sf) != 0:
                continue
            ftface = cr.cairo_ft_scaled_font_lock_face(sf)
            for enc in (b"unic", b"big5", b"sjis"):  # same order as polybar
                if ft.FT_Select_Charmap(ftface, int.from_bytes(enc, "big")) == 0:
                    break
            cr.cairo_ft_scaled_font_unlock_face(sf)
            self.scaled.append(sf)
        if not self.scaled:
            raise RuntimeError("no fonts")
        self.cache = {}

    @staticmethod
    def size(fc, match, dpi):
        """polybar font_fc::size(): font size in px."""
        c = C
        scalable, fsize, fpix = c.c_int(0), c.c_double(0), c.c_double(0)
        fc.FcPatternGetBool(match, b"scalable", 0, c.byref(scalable))
        fc.FcPatternGetDouble(match, b"size", 0, c.byref(fsize))
        fc.FcPatternGetDouble(match, b"pixelsize", 0, c.byref(fpix))
        px_pixelsize = int((fpix.value or 10) + 0.5)
        px_size = int((fsize.value or 10) / 72.0 * dpi + 0.5)
        if fsize.value == 0 and fpix.value == 0:
            return px_size if scalable.value else px_pixelsize
        if scalable.value:
            return px_size if fsize.value != 0 else px_pixelsize
        return px_pixelsize if fpix.value != 0 else px_size

    def width(self, ch):
        """px a char takes in polybar (0 if no font has it: polybar drops it too)."""
        w = self.cache.get(ch)
        if w is None:
            w = 0
            cr = self.cr
            for sf in self.scaled:
                face = cr.cairo_ft_scaled_font_lock_face(sf)
                found = self.ft.FT_Get_Char_Index(face, ord(ch))
                cr.cairo_ft_scaled_font_unlock_face(sf)
                if found:
                    ext = self.Extents()
                    cr.cairo_scaled_font_text_extents(sf, ch.encode("utf-8", "replace"), C.byref(ext))
                    w = math.ceil(ext.x_advance)
                    break
            self.cache[ch] = w
        return w


class Cells:
    """Fallback when fonts can't be loaded: half-width 8px, full-width 16px."""

    def width(self, ch):
        if unicodedata.combining(ch):
            return 0
        return 16 if unicodedata.east_asian_width(ch) in "WF" else 8


def load_fonts():
    specs = []
    for i in range(10):
        spec = ENV.get("MARQUEE_FONT_%d" % i, "").strip()
        if not spec:
            break
        specs.append(spec)
    try:
        return Fonts(specs, DPI)
    except Exception:
        return Cells()


FONTS = None


def textwidth(s):
    return sum(FONTS.width(ch) for ch in s)


def rgb(hexcolor):
    h = hexcolor.lstrip("#")[-6:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


FG_RGB = rgb(FG)


def color(alpha):
    """FG with alpha as #AARRGGBB (bar background is translucent: let polybar blend)."""
    a = min(max(alpha, 0.0), 1.0)
    return "#%02x%02x%02x%02x" % ((round(255 * a),) + FG_RGB)


def smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def offset(px):
    return "%%{O%d}" % px if px else ""


def esc(s):
    return s.replace("%", "%%")


def render_static(text, alpha):
    body = esc(text)
    if text == OFFLINE and text and OFFLINE_FONT.isdigit():
        body = "%%{T%s}%s%%{T-}%s" % (OFFLINE_FONT, esc(text[0]), esc(text[1:]))
    if alpha >= 1:
        return body
    return "%%{F%s}%s%%{F-}" % (color(alpha), body)


class Strip:
    """Title + GAP repeated, laid out per pixel for smooth scrolling."""

    def __init__(self, text):
        self.chars = text + GAP
        self.widths = [FONTS.width(ch) for ch in self.chars]
        self.starts = []
        x = 0
        for w in self.widths:
            self.starts.append(x)
            x += w
        self.length = x

    def render(self, pos, alpha, view, left=1.0):
        """view px of the strip from pos, faded edges (left: left-edge fade, 0 = crisp)."""
        pos %= self.length
        i = bisect.bisect_right(self.starts, pos) - 1
        x = self.starts[i] - pos
        out = [offset(x)]
        last = None
        n = len(self.chars)
        while x < view:
            ch, w = self.chars[i % n], self.widths[i % n]
            i += 1
            if not w:
                continue
            mid = x + w / 2
            fade_l = 1 - left * (1 - smooth(mid / EDGE))
            c = color(alpha * min(fade_l, smooth((view - mid) / EDGE)))
            if c != last:
                out.append("%%{F%s}" % c)
                last = c
            out.append(esc(ch))
            x += w
        out.append("%{F-}")
        out.append(offset(view - x))  # undo the last glyph's overflow: width stays view
        return "".join(out)


def die_with_parent():
    C.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


def spy(*args):
    return subprocess.Popen(["xprop", "-spy", *args], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=XENV, preexec_fn=die_with_parent)


class Reader:
    def __init__(self, proc):
        self.proc, self.buf = proc, b""
        self.fd = proc.stdout.fileno()

    def lines(self):
        chunk = os.read(self.fd, 4096)
        if not chunk:
            return None
        self.buf += chunk
        *done, self.buf = self.buf.split(b"\n")
        return [l.decode("ascii", errors="replace") for l in done]

    def close(self):
        self.proc.kill()
        self.proc.wait()
        self.proc.stdout.close()


def decode(raw):
    """xprop quoted value (\\ooo, \\\", \\\\ escapes) -> text."""
    out = bytearray()
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            octal = re.match(r"[0-7]{1,3}", raw[i + 1:])
            if octal:
                out.append(int(octal.group(), 8) & 0xFF)
                i += 1 + len(octal.group())
                continue
            out += raw[i + 1].encode()
            i += 2
            continue
        out += c.encode()
        i += 1
    text = out.decode("utf-8", errors="replace")
    return re.sub(r"\x1b%[G@]", "", text)  # COMPOUND_TEXT charset switches


def window_prop(props, line):
    m = re.match(r'(_NET_WM_NAME|WM_NAME)\([^)]*\) = "(.*)"$', line)
    if m:
        props[m.group(1)] = " ".join(decode(m.group(2)).split())


def describe(wid, props, seen):
    """Focused window -> text, None while its title hasn't arrived yet."""
    if not wid:
        return OFFLINE
    if not seen:
        return None
    return props.get("_NET_WM_NAME") or props.get("WM_NAME") or OFFLINE


class Marquee:
    def __init__(self, out):
        global FONTS
        FONTS = load_fonts()
        self.out = out
        self.target = self.target_wid = None      # title to show (None = unknown yet), its window
        self.shown = self.shown_wid = self.strip = self.view = None
        self.alpha = 0.0
        self.travel = self.hold_from = self.hold_until = 0.0
        self.looped = False                       # wrapped without pause: keep left edge faded
        self.last = time.monotonic()
        self.root = Reader(spy("-root", "_NET_ACTIVE_WINDOW"))
        self.win, self.wid, self.props, self.seen = None, None, {}, False
        self.focus_known = False

    def fds(self):
        return [self.root.fd] + ([self.win.fd] if self.win else [])

    def timeout(self, now):
        fading = self.target is not None and (self.target != self.shown or self.alpha < 1)
        if fading or (self.strip is not None and now - self.hold_from < FADE):
            return FRAME
        if self.strip is not None:
            return max(FRAME, self.hold_until - now)
        return None

    def handle(self, ready):
        changed = False
        if self.root.fd in ready:
            lines = self.root.lines()
            if lines is None:  # X is gone
                sys.exit(0)
            for line in lines:
                m = re.search(r"window id # (0x[0-9a-f]+)", line)
                w = m.group(1) if m and int(m.group(1), 16) else None
                if self.focus_known and w == self.wid:
                    continue
                self.focus_known, changed = True, True
                if self.win:
                    self.win.close()
                    self.win = None
                self.wid, self.props, self.seen = w, {}, False
                if w:
                    self.win = Reader(spy("-id", w, "_NET_WM_NAME", "WM_NAME"))
        elif self.win and self.win.fd in ready:
            lines = self.win.lines()
            if lines is None:  # window closed: root reports the new focus
                self.win.close()
                self.win = None
            else:
                for line in lines:
                    window_prop(self.props, line)
                self.seen, changed = True, True
        if changed and self.focus_known:
            d = describe(self.wid, self.props, self.seen)
            if d is not None:
                self.target, self.target_wid = d, self.wid

    def tick(self, now):
        dt = min(now - self.last, 2 * FRAME)
        self.last = now
        if self.target is None:
            return
        if self.target != self.shown and self.target_wid == self.shown_wid and self.shown is not None:
            # same window, new title: swap in place, keep the scroll position
            self.shown, self.view = self.target, None
        elif self.target != self.shown:
            self.alpha = max(0.0, self.alpha - dt / FADE) if self.shown is not None else 0.0
            if self.alpha == 0:
                self.shown, self.shown_wid, self.strip, self.view = self.target, self.target_wid, None, None
                self.travel, self.hold_from, self.hold_until = 0.0, now, now + FADE + PAUSE
                self.looped = False
        else:
            self.alpha = min(1.0, self.alpha + dt / FADE)

        if self.view is None:  # re-decide scrolling on a new title, keep the position
            self.view = VIEW
            self.strip = Strip(self.shown) if textwidth(self.shown) > self.view else None
            if self.strip:
                self.travel %= self.strip.length

        if self.strip and now >= self.hold_until:
            self.travel += SPEED * dt
            if self.travel >= self.strip.length:
                if PAUSE > 0:
                    self.travel, self.hold_from, self.hold_until = 0.0, now, now + PAUSE
                else:  # continuous loop
                    self.travel -= self.strip.length
                    self.looped = True

        if self.strip:
            pos = self.travel if DIRECTION == "left" else -self.travel
            # left-edge fade clears during a pause (crisp first letter), returns over EDGE px
            if now < self.hold_until:
                left = 1 - smooth((now - self.hold_from) / FADE)
            elif self.looped:
                left = 1.0
            else:
                left = smooth(self.travel / EDGE)
            out = self.strip.render(round(pos), smooth(self.alpha), self.view, left)
        else:
            out = render_static(self.shown, smooth(self.alpha))

        if out != self.out.line:
            self.out.send(out)


# ---------------------------------------------------------------- main

def main():
    mark = ENV.get("TRAYWIDTH_MARK", "#1BFFFFFF")
    print(f"%{{B{mark}}}%{{O1}}%{{B-}}", flush=True)   # traywidth's only output, 1px wide

    os.makedirs(RUN, exist_ok=True)
    music, notif_out = Fifo("music"), Fifo("notif")
    parts = [Watch([music, notif_out])]
    for f in (music, notif_out):
        f.connect()
    try:
        parts.append(TrayWidth())
    except (OSError, RuntimeError) as e:
        print(f"barsd: {e}", file=sys.stderr)
    parts.append(Notif(notif_out))
    parts.append(Marquee(music))

    while True:
        now = time.monotonic()
        waits = [w for w in (p.timeout(now) for p in parts) if w is not None]
        timeout = min(waits + [SAFETY])
        fds = [fd for p in parts for fd in p.fds()]
        try:
            ready = set(select.select(fds, [], [], max(0.0, timeout))[0])
        except InterruptedError:
            ready = set()
        if os.getppid() != PARENT:
            sys.exit(0)   # polybar is gone
        for p in parts:
            p.handle(ready)
        now = time.monotonic()
        for p in parts:
            p.tick(now)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
