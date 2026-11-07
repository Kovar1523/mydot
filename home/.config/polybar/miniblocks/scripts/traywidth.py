#!/usr/bin/env python3
# polybar 바 길이를 내용에 맞춰 늘이고 줄임 (config.ini [module/traywidth], custom/script tail = true)
# - polybar 3.7에는 실행 중에 폭을 바꾸는 기능이 없음 → 창은 config의 width(= 가장 넓은 상태) 그대로 두고,
#   X Shape로 "보이는 영역"의 왼쪽 경계만 잘라 냄 (picom도 이 모양대로 그리고 blur함, 잘린 곳은 클릭도 통과)
# - 바는 modules-right라 내용이 오른쪽 끝에 붙어 있음 → 음소거·Wi-Fi 끊김 등으로 내용 폭이 바뀌어도
#   시계·벨 같은 글자는 제자리, 유리 배경의 왼쪽 끝만 움직임 (창을 옮기지 않으니 흔들림 없음)
# - 이 모듈(modules-right 맨 앞)은 내용 맨 앞에 1px 표식을 그림 (배경보다 알파만 1/255 높은 세로줄, 눈에는 안 보임)
#   바가 다시 그려질 때만(XDamage) 깨어나 표식 위치를 찾고, 보이는 영역 = 표식 - LEFT px ~ 창 오른쪽 끝
#   표식이 잘린 쪽에 있으면 = 내용이 늘어남 → 전에 맞춰 본 경계 중 더 넓은 것부터 (처음 보는 폭이면 잠깐 전체를)
#   보이게 한 뒤, 다시 그려지면 또 잼 (글자는 안 움직임, 소리 켜기/끄기처럼 아는 폭이면 한 번에 맞음)
# - 경계는 ANIM초 동안 ease-out으로 미끄러짐 (줄 때는 빈 유리가 접히고, 늘 때는 펼쳐지며 아이콘이 드러남)
#   처음 보는 폭은 잠깐(몇 ms) 전체를 열어 재고 원래 경계로 되돌린 뒤 거기서부터 미끄러짐
# - 자기 바 창 = _NET_WM_PID가 부모(polybar) PID인 polybar 창, 바가 다시 시작되면 이 스크립트도 다시 시작됨
# - 환경 변수(config.ini env-*): TRAYWIDTH_LEFT 표식 앞 여백 px (기본 15 = 바 padding 16 - 표식 1),
#   TRAYWIDTH_MARK 표식 색 (바 배경과 아주 조금만 달라야 함, 기본 #1BFFFFFF = 배경 #1AFFFFFF + 알파 1)
import ctypes as C
import os
import select
import sys
import time

LEFT = int(os.environ.get("TRAYWIDTH_LEFT", "15"))
MARK = os.environ.get("TRAYWIDTH_MARK", "#1BFFFFFF")
SETTLE = 0.004       # 다시 그리기가 끝날 때까지 기다리는 시간(초)
ANIM = float(os.environ.get("TRAYWIDTH_ANIM", "0.15"))   # 애니메이션 길이(초), 0 = 바로
FRAME = 1 / 120      # 애니메이션 프레임 간격(초)

# 표식 (이 모듈의 유일한 출력, 폭 1px)
print(f"%{{B{MARK}}}%{{O1}}%{{B-}}", flush=True)

X = C.CDLL("libX11.so.6")
XD = C.CDLL("libXdamage.so.1")
XE = C.CDLL("libXext.so.6")
vp, ul = C.c_void_p, C.c_ulong


class XImage(C.Structure):
    _fields_ = [("width", C.c_int), ("height", C.c_int), ("xoffset", C.c_int), ("format", C.c_int),
                ("data", C.POINTER(C.c_ubyte)), ("byte_order", C.c_int), ("bitmap_unit", C.c_int),
                ("bitmap_bit_order", C.c_int), ("bitmap_pad", C.c_int), ("depth", C.c_int),
                ("bytes_per_line", C.c_int), ("bits_per_pixel", C.c_int)]


class XRectangle(C.Structure):
    _fields_ = [("x", C.c_short), ("y", C.c_short), ("width", C.c_ushort), ("height", C.c_ushort)]


class XEvent(C.Union):
    _fields_ = [("type", C.c_int), ("pad", C.c_long * 24)]


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

DESTROY_NOTIFY = 17
STRUCTURE_NOTIFY_MASK = 1 << 17
DAMAGE_REPORT_NON_EMPTY = 3
Z_PIXMAP = 2
SHAPE_BOUNDING, SHAPE_INPUT, SHAPE_SET, UNSORTED = 0, 2, 0, 0

# 창이 사라진 사이에 요청이 가면 X 오류 → 기본 처리기는 프로세스를 끝냄, 대신 무시하고 아래에서 끝냄
ERROR_HANDLER = C.CFUNCTYPE(C.c_int, vp, vp)(lambda d, e: 0)
X.XSetErrorHandler(C.cast(ERROR_HANDLER, vp))

dpy = X.XOpenDisplay(None)
if not dpy:
    sys.exit("traywidth: no display")
root = X.XDefaultRootWindow(dpy)
NET_WM_PID = X.XInternAtom(dpy, b"_NET_WM_PID", 0)
CARDINAL = 6
PARENT = os.getppid()


def ppid_of(pid):
    try:
        return int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return None


# polybar가 sh -c를 거쳐 실행했을 수도 있어서 부모와 그 부모까지
OWNERS = {PARENT, ppid_of(PARENT)} - {None, 0, 1}


def wm_pid(win):
    t, f, n, a = ul(), C.c_int(), ul(), ul()
    p = C.POINTER(C.c_ubyte)()
    if X.XGetWindowProperty(dpy, win, NET_WM_PID, 0, 1, 0, CARDINAL, C.byref(t), C.byref(f),
                            C.byref(n), C.byref(a), C.byref(p)) != 0 or not p:
        return None
    pid = C.cast(p, C.POINTER(C.c_uint32))[0] if n.value else None
    X.XFree(p)
    return pid


def find_bar():
    r, par, n = ul(), ul(), C.c_uint()
    kids = C.POINTER(ul)()
    if not X.XQueryTree(dpy, root, C.byref(r), C.byref(par), C.byref(kids), C.byref(n)):
        return None
    found = None
    for i in range(n.value):
        w = kids[i]
        name = C.c_char_p()
        if X.XFetchName(dpy, w, C.byref(name)) and name.value:
            ok = name.value.startswith(b"polybar-")
            X.XFree(C.cast(name, vp))
            if ok and wm_pid(w) in OWNERS:
                found = w
                break
    if kids:
        X.XFree(kids)
    return found


def geometry(win):
    r, x, y, w, h, b, d = ul(), C.c_int(), C.c_int(), C.c_uint(), C.c_uint(), C.c_uint(), C.c_uint()
    if not X.XGetGeometry(dpy, win, C.byref(r), C.byref(x), C.byref(y), C.byref(w), C.byref(h), C.byref(b), C.byref(d)):
        return None
    return x.value, y.value, w.value, h.value


# 바 창이 생길 때까지 (바가 막 시작했으면 아직 없음)
bar = None
for _ in range(200):
    bar = find_bar()
    if bar:
        break
    if os.getppid() != PARENT:
        sys.exit(0)
    time.sleep(0.05)
if not bar:
    sys.exit("traywidth: bar window not found")

_, _, W, H = geometry(bar)
left = 0                    # 지금 보이는 영역의 왼쪽 경계 (0 = 전체)
target = 0                  # 가려는 경계
anim = None                 # 애니메이션 중이면 (시작 시각, 시작 경계, 끝 경계)
probe_from = None           # 처음 보는 폭을 재려고 전체를 열었을 때, 원래 경계
first = True                # 처음 맞출 때는 애니메이션 없이
seen = set()                # 전에 맞춰 본 경계들 (음소거·소리 켜짐 등 상태별 폭)


DEBUG = os.environ.get("TRAYWIDTH_DEBUG")
DBGF = open(DEBUG, "a") if DEBUG else None


def set_left(x):
    global left
    if DEBUG:
        print(f"{time.monotonic():.3f} set_left {left} -> {x}", file=DBGF, flush=True)
    left = max(0, min(W - 1, x))
    rect = XRectangle(left, 0, W - left, H)
    for kind in (SHAPE_BOUNDING, SHAPE_INPUT):
        XE.XShapeCombineRectangles(dpy, bar, kind, 0, 0, C.byref(rect), 1, SHAPE_SET, UNSORTED)
    X.XFlush(dpy)


def find_mark():
    """보이는 영역 안에서 표식 열 x (맨 윗줄이 배경과 다른 가장 왼쪽 열), 없으면 -1
    배경 = 오른쪽 끝 맨 윗줄 픽셀 (늘 보이고 글자가 없는 자리), 잘린 곳은 옛 그림이 남아 있을 수 있어 안 봄"""
    img = X.XGetImage(dpy, bar, left, 0, W - left, 1, 0xFFFFFFFF, Z_PIXMAP)
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
            return left + i
    return -1


ev_base, err_base = C.c_int(), C.c_int()
if not XD.XDamageQueryExtension(dpy, C.byref(ev_base), C.byref(err_base)):
    sys.exit("traywidth: no XDamage")
DAMAGE_NOTIFY = ev_base.value
damage = XD.XDamageCreate(dpy, bar, DAMAGE_REPORT_NON_EMPTY)
X.XSelectInput(dpy, bar, STRUCTURE_NOTIFY_MASK)
X.XFlush(dpy)


def animate_to(x, start=None):
    """경계를 x로 (ANIM초 동안 ease-out), start = 출발 경계 (기본 = 지금)"""
    global target, anim
    target = x
    s0 = left if start is None else start
    if ANIM <= 0 or s0 == x:
        anim = None
        if left != x:
            set_left(x)
        return
    anim = (time.monotonic(), s0, x)


def step():
    """애니메이션 한 프레임, 끝나면 False"""
    global anim
    t0, a, b = anim
    t = min(1.0, (time.monotonic() - t0) / ANIM)
    e = 1 - (1 - t) ** 3
    x = round(a + (b - a) * e)
    if x != left:
        set_left(x)
    if t >= 1.0:
        anim = None
        return False
    return True


def fit():
    """다음에 다시 잴 시각 (없으면 None)"""
    global probe_from, first
    m = find_mark()
    if DEBUG:
        print(f"{time.monotonic():.3f} fit left={left} target={target} mark={m}", file=DBGF, flush=True)
    if m is None:
        return None
    if m < 0:
        if anim and target < left:
            return None       # 펼치는 중이라 아직 안 드러남 → 끝나면 다시 잼
        if left == 0:
            return None       # 아직 표식이 안 그려짐 (막 시작) → 다음 다시 그리기 때
        # 표식이 잘린 쪽 = 내용이 늘어남 → 아는 경계 중 바로 더 넓은 것으로
        known = [x for x in seen if x < left]
        if known:
            animate_to(max(known))
            return None
        # 처음 보는 폭: 잠깐 전체를 열어 재고 (다시 그려지면 / 안 그려져도 0.1초 뒤에), 원래 경계에서부터 미끄러짐
        probe_from = left if probe_from is None else probe_from
        globals()["anim"] = None
        set_left(0)
        return time.monotonic() + 0.1
    new = max(0, m - LEFT)
    if len(seen) < 64:
        seen.add(new)
    if probe_from is not None:
        start, probe_from = probe_from, None
        set_left(start)
        animate_to(new, start)
    elif first:
        first = False
        animate_to(new, new)
        if left != new:
            set_left(new)
    elif new != target:
        animate_to(new)
    return None


fd = X.XConnectionNumber(dpy)
ev = XEvent()
pending_fit = time.monotonic()     # 시작하자마자 한 번 맞춤
next_frame = None
while True:
    due = [t for t in (pending_fit, next_frame) if t is not None]
    timeout = None if not due else max(0.0, min(due) - time.monotonic())
    if not X.XPending(dpy):
        select.select([fd], [], [], timeout if timeout is not None else 30)
        if os.getppid() != PARENT:
            sys.exit(0)            # polybar가 끝남
    while X.XPending(dpy):
        X.XNextEvent(dpy, C.byref(ev))
        if ev.type == DAMAGE_NOTIFY:
            XD.XDamageSubtract(dpy, damage, 0, 0)
            soon = time.monotonic() + SETTLE
            if pending_fit is None or pending_fit > soon:
                pending_fit = soon
        elif ev.type == DESTROY_NOTIFY:
            sys.exit(0)
    now = time.monotonic()
    if pending_fit is not None and now >= pending_fit:
        pending_fit = fit()
    if anim:
        if next_frame is None or now >= next_frame:
            if step():
                next_frame = now + FRAME
            else:
                next_frame = None
                pending_fit = time.monotonic()   # 끝나면 한 번 더 잼 (펼친 뒤 표식 확인)
    else:
        next_frame = None
