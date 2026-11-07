#!/usr/bin/env python3
# miniblocks 중앙 타이틀 모듈 (polybar custom/script, tail = true; config.ini 모듈 이름은 원래대로 music)
# 기존 hack 바의 hack/scripts/title-marquee.py처럼 포커스 창의 제목을 그대로 보여 줌 (11-04: 앱별 규칙 없음)
#
# - 표시: 포커스 창의 _NET_WM_NAME (없으면 WM_NAME) = 앱이 정한 제목 그대로
#   예) kitty: 프롬프트에선 현재 디렉터리 (kitty 셸 통합이 제목을 bash의 \w로 바꿈), 명령 실행 중엔 그 명령
#       Firefox: "페이지 제목 — Mozilla Firefox", mpv: "파일 - mpv", 게임: 창 제목
#   포커스 창 없음 (빈 태그) → MARQUEE_OFFLINE. 창 전환·제목 변경은 xprop -spy로 바로 (폴링 없음)
# - 바 안쪽 폭(MARQUEE_VIEW_PX)에 들어가면 그대로 (polybar가 가운데 정렬)
# - 넘치면 픽셀 단위로 부드럽게 흐름: 처음에 MARQUEE_PAUSE초 멈춤 (0이면 멈춤 없이),
#   양 끝 MARQUEE_EDGE_PX는 흐려짐, 다섯 칸 띄우고 반복. 이때 모듈 폭은 항상 MARQUEE_VIEW_PX라 바가 흔들리지 않음
# - 다른 창으로 바뀌면 MARQUEE_FADE초 동안 사라졌다가 나타남,
#   같은 창의 제목만 바뀌면 (kitty 명령, 진행 표시 등) 깜빡이지 않게 그 자리에서 바로 바뀜
# - 글자 폭: polybar 3.7과 같은 방법(fontconfig → cairo, 글꼴별 ceil(x_advance))으로 계산.
#   글꼴은 config.ini의 font-0~3을 env로 받음 (MARQUEE_FONT_0, 1, ...; 비어 있는 번호에서 멈춤)

import bisect
import ctypes
import math
import os
import re
import select
import signal
import subprocess
import time
import unicodedata

VIEW = int(os.environ.get("MARQUEE_VIEW_PX", 560))      # 모듈이 쓸 수 있는 폭 (px)
SPEED = float(os.environ.get("MARQUEE_SPEED", 30))      # 흐르는 속도, px/초
FPS = float(os.environ.get("MARQUEE_FPS", 30))
PAUSE = float(os.environ.get("MARQUEE_PAUSE", 1.5))     # 한 바퀴 시작마다 멈추는 시간 (0 = 멈춤 없이 계속)
FADE = float(os.environ.get("MARQUEE_FADE", 0.2))       # 창이 바뀔 때 사라짐 / 나타남, 각각 초
EDGE = float(os.environ.get("MARQUEE_EDGE_PX", 24))     # 흐를 때 양 끝 흐려지는 폭
DIRECTION = os.environ.get("MARQUEE_DIRECTION", "left")  # 글자가 움직이는 쪽: left / right
FG = os.environ.get("MARQUEE_FG", "#c2c4c6")
OFFLINE = os.environ.get("MARQUEE_OFFLINE", "  offline")
# offline 첫 글자(아이콘)만 그릴 polybar 글꼴 번호 (%{T번호}), 비우면 그대로
OFFLINE_FONT = os.environ.get("MARQUEE_OFFLINE_FONT", "").strip()
DPI = float(os.environ.get("MARQUEE_DPI") or 96)
GAP = "     "                                           # 반복 사이 간격
XENV = dict(os.environ, LC_ALL="C")                     # xprop이 한글 등을 \ooo로 내보내게 (decode)

FRAME = 1 / FPS


class Fonts:
    """polybar 3.7 cairo/font.hpp + context.hpp와 같은 글꼴 고르기·폭 계산."""

    def __init__(self, specs, dpi):
        c = ctypes
        fc = c.CDLL("libfontconfig.so.1")
        cr = c.CDLL("libcairo.so.2")
        ft = c.CDLL("libfreetype.so.6")
        vp = c.c_void_p

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

        self.c, self.cr, self.ft, self.Extents = c, cr, ft, Extents
        if not fc.FcInit():
            raise RuntimeError("FcInit")
        self.scaled = []
        for spec in specs:
            name, _, off = spec.rpartition(";")
            if not name or not off.strip().lstrip("-").replace(".", "").isdigit():
                name = spec  # ";세로 위치"가 없는 경우
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
            for enc in (b"unic", b"big5", b"sjis"):  # polybar와 같은 순서
                if ft.FT_Select_Charmap(ftface, int.from_bytes(enc, "big")) == 0:
                    break
            cr.cairo_ft_scaled_font_unlock_face(sf)
            self.scaled.append(sf)
        if not self.scaled:
            raise RuntimeError("no fonts")
        self.cache = {}

    @staticmethod
    def size(fc, match, dpi):
        """polybar font_fc::size(): 글꼴 크기 (px)."""
        c = ctypes
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
        """글자 하나가 polybar에서 차지하는 px (어느 글꼴에도 없으면 polybar도 버림 → 0)."""
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
                    cr.cairo_scaled_font_text_extents(sf, ch.encode("utf-8", "replace"),
                                                      self.c.byref(ext))
                    w = math.ceil(ext.x_advance)
                    break
            self.cache[ch] = w
        return w


class Cells:
    """글꼴을 못 읽었을 때: 반각 8px, 전각 16px로 어림."""

    def width(self, ch):
        if unicodedata.combining(ch):
            return 0
        return 16 if unicodedata.east_asian_width(ch) in "WF" else 8


def load_fonts():
    specs = []
    for i in range(10):
        spec = os.environ.get("MARQUEE_FONT_%d" % i, "").strip()
        if not spec:
            break
        specs.append(spec)
    try:
        return Fonts(specs, DPI)
    except Exception:
        return Cells()


FONTS = load_fonts()


def textwidth(s):
    return sum(FONTS.width(ch) for ch in s)


def rgb(hexcolor):
    h = hexcolor.lstrip("#")[-6:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


FG_RGB = rgb(FG)


def color(alpha):
    """글자색에 알파(0~1)를 준 #AARRGGBB.
    바 배경이 반투명(+ picom blur)이라 배경색에 섞지 않고 polybar가 뒤 화면 위에 겹쳐 그리게 함
    (배경이 불투명하면 섞은 것과 같음)."""
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
    """GAP을 붙여 반복하는 제목, 픽셀 단위로 배치 (부드럽게 흐르게)."""

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
        """반복 띠의 pos px부터 view px만큼 그림, 양 끝은 흐리게
        (left: 왼쪽 끝 흐림 정도, 0이면 안 흐림 = 멈춰서 제목 시작을 보여 줄 때)."""
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
        out.append(offset(view - x))  # 마지막 글자가 넘친 만큼 되돌림 → 폭이 늘 view
        return "".join(out)


def die_with_parent():
    ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG


def spy(*args):
    return subprocess.Popen(["xprop", "-spy", *args], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=XENV, preexec_fn=die_with_parent)


class Reader:
    def __init__(self, proc):
        self.proc, self.buf = proc, b""

    def lines(self):
        chunk = os.read(self.proc.stdout.fileno(), 4096)
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
    """xprop의 따옴표 안 값(\\ooo, \\\", \\\\ 이스케이프) → 글자 (hack/scripts/title-marquee.py와 같음)."""
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
    return re.sub(r"\x1b%[G@]", "", text)  # COMPOUND_TEXT 문자 집합 전환


def window_prop(props, line):
    """xprop -spy -id 한 줄 → props에 제목 반영."""
    m = re.match(r'(_NET_WM_NAME|WM_NAME)\([^)]*\) = "(.*)"$', line)
    if m:
        props[m.group(1)] = " ".join(decode(m.group(2)).split())  # 줄바꿈·탭은 공백 하나로


def describe(wid, props, seen):
    """포커스 창 → 보여 줄 글자, 창 제목을 아직 못 받았으면 None."""
    if not wid:
        return OFFLINE
    if not seen:
        return None
    return props.get("_NET_WM_NAME") or props.get("WM_NAME") or OFFLINE


def main():
    target, target_wid = None, None  # 보여야 할 제목 (None = 아직 모름), 그 창
    shown, shown_wid, strip, view = None, None, None, None
    alpha = 0.0
    travel, hold_from, hold_until = 0.0, 0.0, 0.0
    looped = False                  # 멈춤 없이 한 바퀴 넘어감 (이후 왼쪽 끝은 계속 흐림)
    last_out = None
    last = time.monotonic()
    root = Reader(spy("-root", "_NET_ACTIVE_WINDOW"))  # 포커스 창 (dwm이 바꿈)
    win, wid, props, seen = None, None, {}, False       # 포커스 창의 xprop, id, 제목, 받았는지
    focus_known = False

    while True:
        now = time.monotonic()

        fading = target is not None and (target != shown or alpha < 1)
        if fading or (strip is not None and now - hold_from < FADE):
            timeout = FRAME
        elif strip is not None:
            timeout = max(FRAME, hold_until - now)
        else:
            timeout = None  # 다음 창 전환·제목 변경까지

        fds = [root.proc.stdout] + ([win.proc.stdout] if win else [])
        ready, _, _ = select.select(fds, [], [], timeout)
        changed = False
        for f in ready:
            if f is root.proc.stdout:
                lines = root.lines()
                if lines is None:  # X가 끝남
                    return
                for line in lines:
                    m = re.search(r"window id # (0x[0-9a-f]+)", line)
                    w = m.group(1) if m and int(m.group(1), 16) else None
                    if focus_known and w == wid:
                        continue
                    focus_known, changed = True, True
                    if win:
                        win.close()
                        win = None
                    wid, props, seen = w, {}, False
                    if w:
                        win = Reader(spy("-id", w, "_NET_WM_NAME", "WM_NAME"))
            elif win and f is win.proc.stdout:
                lines = win.lines()
                if lines is None:  # 창이 닫힘: 새 포커스는 root 쪽이 알려 줌
                    win.close()
                    win = None
                    continue
                for line in lines:
                    window_prop(props, line)
                seen, changed = True, True
        if changed and focus_known:
            d = describe(wid, props, seen)
            if d is not None:
                target, target_wid = d, wid

        now = time.monotonic()
        dt = min(now - last, 2 * FRAME)
        last = now

        if target is None:
            continue
        if target != shown and target_wid == shown_wid and shown is not None:
            # 같은 창의 제목만 바뀜 (kitty 명령, 진행 표시 등): 페이드 없이 바로, 흐르던 위치는 유지
            shown, view = target, None
        elif target != shown:
            alpha = max(0.0, alpha - dt / FADE) if shown is not None else 0.0
            if alpha == 0:
                shown, shown_wid, strip, view = target, target_wid, None, None
                travel, hold_from, hold_until = 0.0, now, now + FADE + PAUSE
                looped = False
        else:
            alpha = min(1.0, alpha + dt / FADE)

        if view is None:  # 제목이 바뀌면 흐를지 다시 판단, 흐르던 위치는 유지
            view = VIEW
            strip = Strip(shown) if textwidth(shown) > view else None
            if strip:
                travel %= strip.length

        if strip and now >= hold_until:
            travel += SPEED * dt
            if travel >= strip.length:
                if PAUSE > 0:
                    travel, hold_from, hold_until = 0.0, now, now + PAUSE
                else:  # 멈춤 없음 (11-03): 넘친 만큼 그대로 이어서 = 끊김 없는 반복
                    travel -= strip.length
                    looped = True

        if strip:
            pos = travel if DIRECTION == "left" else -travel
            # 왼쪽 끝 흐림: 멈춘 동안 FADE초에 걸쳐 걷히고 (제목 첫 글자가 또렷하게),
            # 다시 흐르면 EDGE px 움직이는 동안 돌아옴 (기존 title-marquee.py는 멈춰도 흐렸음)
            # 멈춤 없이 이어서 돌 때는 바퀴가 바뀌어도 계속 흐림 (경계에서 번쩍이지 않게)
            if now < hold_until:
                left = 1 - smooth((now - hold_from) / FADE)
            elif looped:
                left = 1.0
            else:
                left = smooth(travel / EDGE)
            out = strip.render(round(pos), smooth(alpha), view, left)
        else:
            out = render_static(shown, smooth(alpha))

        if out != last_out:
            print(out, flush=True)
            last_out = out


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: exit(0))
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
