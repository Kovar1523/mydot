#!/usr/bin/env python3
# Notification center (rofi script mode) for the bell icon at the right end of polybar.
# Lists dunst's history (newest first) as cards grouped by date in rofi/notifcenter.rasi (584px).
#   Enter / left click     pop the notification again (dunst shows it in full) and close
#   Delete / right click   remove it from the history; the list stays open
#   clear (Alt+c, click)   the first press asks in the status text, the second clears the whole history
#   dnd (Alt+d, click)     toggle do-not-disturb
#   typing                 filters the list (Search box); date headers hide while searching
# Started by polybar (no ROFI_RETV) it opens rofi with itself as the script mode. rofi runs it again
# after every action and keeps the window open while it prints rows (no rows = rofi closes).

import datetime
import glob
import html
import os
import re
import sys
import time

import gi
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gio, GLib, Pango, PangoCairo

DUNST = "org.freedesktop.Notifications"
PATH = "/org/freedesktop/Notifications"
IFACE = "org.dunstproject.cmd0"
THEME = os.path.expanduser("~/.config/polybar/miniblocks/scripts/rofi/notifcenter.rasi")
SEP = "\x01"          # row delimiter: rows are two lines (summary + body)
CRIT = "#BF616A"      # palette red: clear confirm (critical cards get a red bar in the theme)
BTN = "#FFFFFF26"     # button background, as in notifcenter.rasi
BTN_ON = "#FFFFFF40"  # dnd on
HEADER = "​"     # header row text: never matches a search, so headers hide while filtering

# app icons come from this theme only (rofi's icon-theme in notifcenter.rasi is the same)
ICON_THEME = "/usr/share/icons/Nordzy-turquoise-dark"
ICON_DIRS = ("apps", "status", "devices", "categories", "places", "mimes", "actions")
ICON_FALLBACK = "preferences-system-notifications"

# must match notifcenter.rasi: font, text width of a card and the tab stop of the time column
FONT = "JetBrainsMono Nerd Font Mono, Pretendard 10.5"
CELL = 8
LINE_PX = 494
TIME_PX = 7 * CELL    # time column right of the tab stop; "5시간 전" is 48px
WEEKDAYS = "월화수목금토일"
# span sizes whose space is 1-7px wide in FONT, to right-align text to the pixel
PAD_FONT = "JetBrainsMono Nerd Font Mono"
SPACE = {1: 1024, 2: 2048, 3: 3584, 4: 4608, 5: 6144, 6: 7168, 7: 8704}
GAP_PX = 2 * CELL

bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
layout = Pango.Layout.new(PangoCairo.FontMap.get_default().create_context())
layout.set_font_description(Pango.FontDescription.from_string(FONT))


def call(method, args=None, iface=IFACE):
    return bus.call_sync(DUNST, PATH, iface, method, args, None,
                         Gio.DBusCallFlags.NONE, 2000, None).unpack()


def prop(name):
    return call("Get", GLib.Variant("(ss)", (IFACE, name)), "org.freedesktop.DBus.Properties")[0]


def set_paused(value):
    call("Set", GLib.Variant("(ssv)", (IFACE, "paused", GLib.Variant("b", value))),
         "org.freedesktop.DBus.Properties")


def clean(text):
    # dunst runs with markup = full, so bodies may carry pango tags; show them as plain text
    # only real tags: "<->" in a title is text, not markup
    return " ".join(html.unescape(re.sub(r"</?[A-Za-z][^>]*>", "", text)).split())


def esc(text):
    return GLib.markup_escape_text(text)


def width(markup):
    layout.set_markup(markup, -1)
    return layout.get_pixel_size()[0]


def fit_bold(text, px):
    # bold summary cut with … so the time column after the tab stays on the line
    if width(f"<b>{esc(text)}</b>") <= px:
        return esc(text)
    while text and width(f"<b>{esc(text)}…</b>") > px:
        text = text[:-1]
    return esc(text.rstrip()) + "…"


def rjust_px(markup, px):
    # Hangul is wider than a cell, so pad by measured pixels instead of characters
    gap = max(0, px - width(markup))
    pad = " " * (gap // CELL)
    if gap % CELL:
        pad += f"<span size='{SPACE[gap % CELL]}'> </span>"
    # pin the pad to the Latin font: spaces next to Hangul would fall back to Pretendard (4px)
    return f"<span font_family='{PAD_FONT}'>{pad}</span>{markup}" if pad else markup


def theme_icon(name):
    # absolute path of a Nordzy icon, scalable first; None if the theme has no such icon
    if not name or "/" in name:
        return None
    hits = []
    for d in ICON_DIRS:
        hits += glob.glob(f"{ICON_THEME}/{d}/*/{glob.escape(name)}.svg")
    hits.sort(key=lambda p: "/scalable/" not in p)
    return hits[0] if hits else None


def icon(n):
    # the sender's icon name or file stem, then the app name, mapped onto Nordzy
    path = n.get("icon_path", "")
    if path.startswith(ICON_THEME + "/"):
        return path
    app = clean(n.get("appname", "")).lower()
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    for name in (stem, app, app.replace(" ", "-"), app.split(" ")[0] if app else ""):
        found = theme_icon(name)
        if found:
            return found
    return theme_icon(ICON_FALLBACK) or ICON_FALLBACK


def posted(ts_us):
    # dunst timestamps are g_get_monotonic_time() (CLOCK_MONOTONIC, microseconds) -> wall clock
    return time.time() - (time.clock_gettime(time.CLOCK_MONOTONIC) - ts_us / 1e6)


def day_label(day):
    today = datetime.date.today()
    if day == today:
        return "오늘"
    if day == today - datetime.timedelta(days=1):
        return "어제"
    return f"{day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]})"


def age(t, today):
    # relative for the last hours of today, clock time otherwise (the header has the date)
    sec = time.time() - t
    if today and sec < 60:
        return "방금"
    if today and sec < 3600:
        return f"{int(sec // 60)}분 전"
    if today and sec < 6 * 3600:
        return f"{int(sec // 3600)}시간 전"
    return time.strftime("%H:%M", time.localtime(t))


def card(n, today):
    summary = clean(n.get("summary", "")) or clean(n.get("appname", ""))
    body = clean(n.get("body", ""))
    app = clean(n.get("appname", ""))
    title = fit_bold(summary, LINE_PX - TIME_PX - GAP_PX)
    when = rjust_px(esc(age(posted(n.get("timestamp", 0)), today)), TIME_PX)
    # no body (e.g. a one-line error): show the app name dimmed instead of an empty line
    second = esc(body) if body else f"<span fgalpha='60%'>{esc(app)}</span>"
    display = f"<b>{title}</b>\t<span fgalpha='60%'>{when}</span>\n{second}"
    urgent = "true" if n.get("urgency") == "CRITICAL" else "false"
    # the plain text is what the Search box filters on; display is what is drawn
    return (f"{summary} {body} {app}\0display\x1f{display}\x1ficon\x1f{icon(n)}"
            f"\x1furgent\x1f{urgent}\x1finfo\x1f{n['id']}")


def header(text):
    # second line only, so the label sits right above its first card
    return (f"{HEADER}\0display\x1f\n<span fgalpha='60%'><b>{esc(text)}</b></span>"
            "\x1fnonselectable\x1ftrue\x1factive\x1ftrue")


def empty_row(text):
    return (f"{text}\0display\x1f<span fgalpha='60%'>{esc(text)}</span>"
            "\x1fnonselectable\x1ftrue\x1fpermanent\x1ftrue\x1factive\x1ftrue")


def build(history):
    # rows with date headers; ids[i] is the notification id of row i (None for headers)
    rows, ids, last = [], [], None
    for n in history:
        day = datetime.date.fromtimestamp(posted(n.get("timestamp", 0)))
        if day != last:
            rows.append(header(day_label(day)))
            ids.append(None)
            last = day
        rows.append(card(n, day == datetime.date.today()))
        ids.append(n["id"])
    return rows, ids


def status(count, paused, waiting, confirm):
    # status text in the input bar: count, queued while dnd, or the clear question
    if confirm:
        return f"<span color='{CRIT}'>{count}개를 모두 지울까요?</span> 한 번 더 누르세요"
    if paused and waiting:
        return f"<span fgalpha='60%'>대기 {waiting} ·</span> total: {count}"
    return f"total: {count}"


def theme(paused, confirm):
    # script-mode theme snippets may only change colors of widgets that are redrawn
    return (f"button-clear {{ text-color: {CRIT if confirm else '@fg'}; }}\n"
            f"button-dnd {{ background-color: {BTN_ON if paused else BTN}; "
            f"text-color: {'@ac' if paused else '@fg'}; }}")


def launch():
    # extra arguments go to rofi after the theme, e.g. miniblocks (top bar) moves the window:
    #   notif-center.py -theme-str 'window { location: north east; ... }'
    os.execvp("rofi", ["rofi", "-no-config", "-no-lazy-grab", "-show", "notif",
                       "-modes", f"notif:{os.path.abspath(sys.argv[0])}",
                       "-eh", "2", "-hover-select",
                       "-selected-row", "1",   # row 0 is the first date header

                       "-me-select-entry", "", "-me-accept-entry", "MousePrimary",
                       "-kb-remove-char-forward", "Control+d",
                       "-kb-custom-1", "Delete,MouseSecondary",
                       "-kb-custom-2", "Alt+c", "-kb-custom-3", "Alt+d",
                       "-theme", THEME] + sys.argv[1:])


def mode():
    retv = int(os.environ["ROFI_RETV"])
    info = os.environ.get("ROFI_INFO", "")
    nid = int(info) if info.isdigit() else None
    out = ["\0delim\x1f\x01\n"] if retv == 0 else []   # rofi remembers it; sending it again breaks parsing
    opts = ["markup-rows\x1ftrue", "use-hot-keys\x1ftrue", "no-custom\x1ffalse"]
    try:
        (history,) = call("NotificationListHistory")
        confirm, select = False, None
        if retv == 1 and nid is not None:              # Enter / left click
            call("NotificationPopHistory", GLib.Variant("(u)", (nid,)))
            return                                      # no rows: rofi closes
        if retv in (3, 10) and nid is not None:        # Shift+Delete, Delete / right click
            old = [n["id"] for n in history]
            call("NotificationRemoveFromHistory", GLib.Variant("(u)", (nid,)))
            if nid in old:
                select = old.index(nid)
                history = [n for n in history if n["id"] != nid]
        elif retv == 11 and history:                   # clear: ask first, clear on the second press
            if os.environ.get("ROFI_DATA") == "confirm":
                call("NotificationClearHistory")
                history = []
            else:
                confirm = True
        elif retv == 12:                               # dnd
            set_paused(not prop("paused"))
        paused, waiting = prop("paused"), prop("waitingLength")
    except GLib.Error as e:
        sys.stdout.write("".join(out) + SEP.join(
            f"\0{o}" for o in opts) + SEP + empty_row(f"dunst에 연결할 수 없음: {e.message}"))
        return
    rows, ids = build(history)
    if not rows:
        rows, ids = [empty_row("알림 없음")], [None]
    opts += [f"data\x1f{'confirm' if confirm else '-'}",
             f"prompt\x1f{status(len(history), paused, waiting, confirm)}",
             f"theme\x1f{theme(paused, confirm)}"]
    if retv != 0:
        # stay on the same row (after a delete: the card that moved into its place), keep the search text
        opts += ["keep-selection\x1ftrue", "keep-filter\x1ftrue"]
        if select is not None and history:
            target = history[min(select, len(history) - 1)]["id"]
            opts.append(f"new-selection\x1f{ids.index(target)}")
    sys.stdout.write("".join(out) + "".join(f"\0{o}{SEP}" for o in opts) + SEP.join(rows))


if __name__ == "__main__":
    if "ROFI_RETV" in os.environ:
        mode()
    else:
        launch()
