#!/usr/bin/env python3
# Notification center for the bell icon at the right end of polybar (eww window "notifcenter",
# ~/.config/eww/notifcenter.yuck + notifcenter.scss). Cards = dunst history (newest first) grouped
# by date, pinned cards on top.
#   left click        expand / collapse the card (eww var nc_exp, no round trip through here)
#   right click       slide the card left and show pin / delete / copy (eww var nc_opt)
#   clear button      the first press asks in the status text, the second clears the history
#                     (pinned cards stay)
#   dnd button        toggle do-not-disturb
#   click outside, Esc  close
# Pinned cards are copies in ~/.local/state/notif-center/pins.json, so they survive clear,
# dunst's history_length and dunst restarts.
#
#   notif-center.py                 toggle (polybar click); stays as the watcher while open
#   notif-center.py pin|delete|copy KEY, clear, dnd     (eww buttons)
# Env for tests: NC_EWW (eww command), NC_STATE (pins dir).

import ctypes
import datetime
import html
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
import unicodedata

EWW = os.environ.get("NC_EWW", "eww").split()
WINDOW = "notifcenter"
STATE = os.environ.get("NC_STATE", os.path.expanduser("~/.local/state/notif-center"))
PINS = os.path.join(STATE, "pins.json")
RUN = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "notif-center")
PIDFILE = RUN + ".pid"
CLOSED = RUN + ".closed"     # mtime = last close by the watcher (click on the bell itself)
LAST = RUN + ".json"         # last pushed data, shared by the watcher and the buttons
FLASH = RUN + ".flash"       # mtime = last copy, shown as "복사됨" for a moment

# app icons come from this theme only
ICON_THEME = "/usr/share/icons/Nordzy-turquoise-dark"
ICON_DIRS = ("apps", "status", "devices", "categories", "places", "mimes", "actions")
ICON_FALLBACK = "preferences-system-notifications"
WEEKDAYS = "월화수목금토일"

# must match notifcenter.scss: collapsed card, date label, list spacing; scroll above LIST_MAX
CARD_H = 60
HEAD_H = 18
GAP = 6
LIST_MAX = 700
BODY_MAX = 1500
# card text width (notifcenter.scss); 14px glyphs: JetBrains Mono 8.4px, Pretendard Hangul 12.1px
TEXT_PX = 494


# ---------- data ----------

def run(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3, **kw).stdout


def eww(*args):
    subprocess.run(EWW + list(args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)


def is_open():
    return any(line.split(":")[0] == WINDOW for line in run(*EWW, "active-windows").splitlines())


def posted(ts_us):
    # dunst timestamps are g_get_monotonic_time() (microseconds) -> wall clock
    return time.time() - (time.clock_gettime(time.CLOCK_MONOTONIC) - ts_us / 1e6)


def strip_tags(text):
    # dunst runs with markup = full; only real tags, so "<->" in a title stays
    return html.unescape(re.sub(r"</?[A-Za-z][^>]*>", "", text))


def flat(text):
    return " ".join(strip_tags(text).split())


def block(text):
    # keep line breaks, at most one blank line in a row
    lines = [" ".join(l.split()) for l in strip_tags(text).splitlines()]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out if len(out) <= BODY_MAX else out[:BODY_MAX].rstrip() + "…"


def hangul(c):
    return "\uac00" <= c <= "\ud7a3" or "\u3130" <= c <= "\u318f"


def px(text):
    # a space after Hangul is drawn in Pretendard (3.6px), like the Hangul before it
    total, prev = 0.0, ""
    for c in text:
        if c == " ":
            total += 3.6 if hangul(prev) else 8.4
            continue
        total += 12.2 if hangul(c) else 14 if unicodedata.east_asian_width(c) in "WF" else 8.4
        prev = c
    return total


def wrap(text, width=TEXT_PX, first=None):
    # lines that fit the card; eww labels don't wrap here (a wrapping label breaks the
    # window's height-for-width), so the expanded text arrives already broken.
    # first = narrower width of the first line (title row next to the time)
    out = []
    for para in text.split("\n"):
        line = ""
        for word in re.findall(r"\S+\s*", para) or [""]:
            width_now = first if first and not out else width
            if px(line + word.rstrip()) <= width_now:
                line += word
                continue
            if line:
                out.append(line.rstrip())
                line = ""
            while px(word.rstrip()) > width:          # a path or URL longer than a line
                cut = len(word)
                while px(word[:cut]) > (first if first and not out else width):
                    cut -= 1
                out.append(word[:cut])
                word = word[cut:]
            line = word
        out.append(line.rstrip() or " ")
    return out


def theme_icon(name):
    if not name or "/" in name:
        return None
    hits = []
    for d in ICON_DIRS:
        for size in ("scalable", "48", "32", "24"):
            p = f"{ICON_THEME}/{d}/{size}/{name}.svg"
            if os.path.exists(p):
                hits.append(p)
    return hits[0] if hits else None


def icon(path, app):
    if path.startswith(ICON_THEME + "/"):
        return path
    app = flat(app).lower()
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    for name in (stem, app, app.replace(" ", "-"), app.split(" ")[0] if app else ""):
        found = theme_icon(name)
        if found:
            return found
    return theme_icon(ICON_FALLBACK) or ""


def history(raw=None):
    try:
        data = json.loads(raw if raw is not None else run("dunstctl", "history"))["data"][0]
    except (ValueError, KeyError, IndexError, subprocess.SubprocessError):
        return []
    out = []
    for n in data:
        n = {k: v.get("data") for k, v in n.items()}
        out.append({"k": f"d{n['id']}", "id": n["id"], "posted": posted(n.get("timestamp", 0)),
                    "summary": n.get("summary", ""), "body": n.get("body", ""),
                    "app": n.get("appname", ""), "icon": icon(n.get("icon_path", ""), n.get("appname", "")),
                    "urgent": n.get("urgency") == "CRITICAL"})
    return out


def load_pins():
    try:
        with open(PINS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_pins(pins):
    os.makedirs(STATE, exist_ok=True)
    tmp = PINS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(pins, f, ensure_ascii=False)
    os.replace(tmp, PINS)


def same(pin, n):
    # dunst ids restart with dunst, so match the post time as well
    return pin["id"] == n["id"] and abs(pin["posted"] - n["posted"]) < 2


# ---------- eww data ----------

def day_label(day):
    today = datetime.date.today()
    if day == today:
        return "오늘"
    if day == today - datetime.timedelta(days=1):
        return "어제"
    return f"{day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]})"


def age(t):
    sec = time.time() - t
    today = datetime.date.fromtimestamp(t) == datetime.date.today()
    if today and sec < 60:
        return "방금"
    if today and sec < 3600:
        return f"{int(sec // 60)}분 전"
    if today and sec < 6 * 3600:
        return f"{int(sec // 3600)}시간 전"
    if today:
        return time.strftime("%H:%M", time.localtime(t))
    lt = time.localtime(t)
    return f"{lt.tm_mon}/{lt.tm_mday} {lt.tm_hour:02d}:{lt.tm_min:02d}"


def card(r, pinned):
    app = flat(r["app"])
    body = block(r["body"])
    title = flat(r["summary"]) or app
    ago = age(r["posted"])
    lt = time.localtime(r["posted"])
    when = f"{lt.tm_mon}월 {lt.tm_mday}일 {lt.tm_hour:02d}:{lt.tm_min:02d}"
    head = wrap(title, first=TEXT_PX - 16 - px(ago))
    return {"k": r["k"], "title": title, "title1": head[0], "head": head[1:],
            "time": ago,
            "short": flat(r["body"]) or app, "dim": not body,
            "lines": wrap(body) if body else [],
            "meta": f"{app} · {when}" if app else when,
            "icon": r["icon"], "urgent": r["urgent"], "pinned": pinned}


def build():
    # the three dunstctl calls run side by side
    procs = [subprocess.Popen(c, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
             for c in (["dunstctl", "history"], ["dunstctl", "is-paused"], ["dunstctl", "count", "waiting"])]
    raw, paused, waiting = (p.communicate(timeout=3)[0].strip() for p in procs)
    hist, pins = history(raw), load_pins()
    groups = []
    if pins:
        groups.append({"label": "고정됨", "items": [card(p, True) for p in pins]})
    last, rest = None, [n for n in hist if not any(same(p, n) for p in pins)]
    for n in rest:
        day = datetime.date.fromtimestamp(n["posted"])
        if day != last:
            groups.append({"label": day_label(day), "items": []})
            last = day
        groups[-1]["items"].append(card(n, False))
    count = len(pins) + len(rest)
    paused = paused == "true"
    status = f"total: {count}"
    if paused and waiting not in ("", "0"):
        status = f"대기 {waiting} · {status}"
    try:
        if time.time() - os.path.getmtime(FLASH) < 1.5:
            status = "복사됨"
    except OSError:
        pass
    height = sum(HEAD_H + GAP + len(g["items"]) * (CARD_H + GAP) for g in groups)
    return {"groups": groups, "count": count, "clearn": len(rest), "status": status,
            "paused": paused, "empty": count == 0, "scroll": height > LIST_MAX}


def push(data, *extra):
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    try:
        with open(LAST) as f:
            if f.read() == text and not extra:
                return
    except OSError:
        pass
    with open(LAST, "w") as f:
        f.write(text)
    eww("update", f"nc={text}", *extra)


# ---------- actions (eww buttons) ----------

def find(key):
    for p in load_pins():
        if p["k"] == key:
            return p, True
    for n in history():
        if n["k"] == key:
            return n, False
    return None, False


def action(cmd, key=None):
    r, pinned = find(key) if key else (None, False)
    if cmd == "pin" and r:
        pins = load_pins()
        if pinned:
            pins = [p for p in pins if p["k"] != key]
        else:
            pins.insert(0, dict(r, k=f"p{r['id']}-{int(r['posted'])}"))
        save_pins(pins)
    elif cmd == "delete" and r:
        if pinned:
            save_pins([p for p in load_pins() if p["k"] != key])
        for n in history():
            if (pinned and same(r, n)) or n["k"] == key:
                run("dunstctl", "history-rm", str(n["id"]))
    elif cmd == "copy" and r:
        text = flat(r["summary"]) + ("\n" + block(r["body"]) if r["body"] else "")
        subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        open(FLASH, "w").close()
    elif cmd == "clear":
        run("dunstctl", "history-clear")
    elif cmd == "dnd":
        run("dunstctl", "set-paused", "toggle")
    push(build(), "nc_opt=", "nc_confirm=false")


# ---------- toggle + watcher ----------

class Cookie(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("extension", ctypes.c_int), ("evtype", ctypes.c_int),
                ("cookie", ctypes.c_uint), ("data", ctypes.c_void_p)]


class RawEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("extension", ctypes.c_int), ("evtype", ctypes.c_int),
                ("time", ctypes.c_ulong), ("deviceid", ctypes.c_int), ("sourceid", ctypes.c_int),
                ("detail", ctypes.c_int), ("flags", ctypes.c_int)]


class EventMask(ctypes.Structure):
    _fields_ = [("deviceid", ctypes.c_int), ("mask_len", ctypes.c_int),
                ("mask", ctypes.POINTER(ctypes.c_ubyte))]


def close(by_watcher=False):
    if by_watcher:
        open(CLOSED, "w").close()   # before closing, so a bell click that caused it sees it
    eww("close", WINDOW)


def watcher():
    # pid of the running watcher (= the window is open), or None
    try:
        with open(PIDFILE) as f:
            pid = int(f.read())
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            if b"notif-center.py" in f.read() and pid != os.getpid():
                return pid
    except (OSError, ValueError):
        pass
    return None


def toggle():
    pid = watcher()
    if pid:
        os.kill(pid, signal.SIGTERM)
        close()
        return
    try:
        if time.time() - os.path.getmtime(CLOSED) < 0.4:
            return                  # this click on the bell already closed it
    except OSError:
        pass
    try:
        os.remove(LAST)             # always push on open
    except OSError:
        pass
    push(build(), "nc_exp=", "nc_opt=", "nc_confirm=false")
    eww("open", WINDOW)
    watch()


def is_center(x11, dpy, win):
    # top-level window under the pointer is an eww notifcenter window (by title, so a
    # re-created window or a second daemon's copy still counts)
    name = ctypes.c_char_p()
    if not win or not x11.XFetchName(dpy, ctypes.c_ulong(win), ctypes.byref(name)) or not name.value:
        return False
    hit = name.value == f"Eww - {WINDOW}".encode()
    x11.XFree(name)
    return hit


def watch():
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    x11 = ctypes.CDLL("libX11.so.6")
    xi = ctypes.CDLL("libXi.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    for fn in ("XDefaultRootWindow", "XFetchName", "XFree", "XQueryPointer",
               "XGrabKeyboard", "XPending", "XNextEvent", "XConnectionNumber", "XKeysymToKeycode",
               "XQueryExtension", "XGetEventData", "XFreeEventData", "XFlush"):
        getattr(x11, fn).argtypes = None
    dpy = ctypes.c_void_p(x11.XOpenDisplay(None))
    if not dpy:
        return
    handler = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(lambda d, e: 0)
    x11.XSetErrorHandler(handler)
    root = ctypes.c_ulong(x11.XDefaultRootWindow(dpy))

    # outside clicks: XInput2 raw button presses (the pointer stays free for the window)
    op, ev_base, err_base = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
    x11.XQueryExtension(dpy, b"XInputExtension", ctypes.byref(op), ctypes.byref(ev_base), ctypes.byref(err_base))
    major, minor = ctypes.c_int(2), ctypes.c_int(0)
    xi.XIQueryVersion(dpy, ctypes.byref(major), ctypes.byref(minor))
    bits = (ctypes.c_ubyte * 4)()
    bits[15 >> 3] |= 1 << (15 & 7)             # XI_RawButtonPress
    mask = EventMask(1, 4, bits)               # XIAllMasterDevices
    xi.XISelectEvents(dpy, root, ctypes.byref(mask), 1)

    # Esc: grab the keyboard while open, like rofi did
    esc = x11.XKeysymToKeycode(dpy, ctypes.c_ulong(0xFF1B))
    for _ in range(40):
        if x11.XGrabKeyboard(dpy, root, 1, 1, 1, ctypes.c_ulong(0)) == 0:
            break
        time.sleep(0.025)

    event = (ctypes.c_long * 24)()
    fd = x11.XConnectionNumber(dpy)
    next_tick = time.monotonic() + 1
    while True:
        while x11.XPending(dpy):
            x11.XNextEvent(dpy, ctypes.byref(event))
            etype = ctypes.c_int.from_buffer(event).value
            if etype == 2 and ctypes.c_uint.from_buffer(event, 84).value == esc:   # KeyPress
                close(True)
                return
            if etype == 35:                                                       # GenericEvent
                cookie = Cookie.from_buffer(event)
                if cookie.extension != op.value or not x11.XGetEventData(dpy, ctypes.byref(cookie)):
                    continue
                button = ctypes.cast(cookie.data, ctypes.POINTER(RawEvent)).contents.detail
                x11.XFreeEventData(dpy, ctypes.byref(cookie))
                if button not in (1, 2, 3):
                    continue                    # wheel and side buttons don't close
                r, child = ctypes.c_ulong(), ctypes.c_ulong()
                rx, ry, wx, wy, m = (ctypes.c_int() for _ in range(5))
                x11.XQueryPointer(dpy, root, ctypes.byref(r), ctypes.byref(child), ctypes.byref(rx),
                                  ctypes.byref(ry), ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(m))
                if not is_center(x11, dpy, child.value):
                    close(True)
                    return
        wait = next_tick - time.monotonic()
        if wait > 0:
            select.select([fd], [], [], wait)
        if time.monotonic() >= next_tick:
            next_tick = time.monotonic() + 1
            if not is_open():
                return
            push(build())


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))   # run the pidfile cleanup below
    try:
        if len(sys.argv) > 1:
            action(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
        else:
            toggle()
    finally:
        try:
            with open(PIDFILE) as f:
                if int(f.read()) == os.getpid():
                    os.remove(PIDFILE)
        except (OSError, ValueError):
            pass
