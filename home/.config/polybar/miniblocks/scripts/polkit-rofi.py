#!/usr/bin/env python3
# polkit 인증 창 — .xinitrc의 `cmd-polkit-agent -s -c <이 파일>`이 인증 요청마다 실행한다.
# stdin으로 JSON 한 줄씩 받음: request password / show error / show info (PAM 메시지) / authorization response.
# 인증이 끝나거나 취소되면 cmd-polkit이 stdin을 닫는다(EOF). stdout으로 authenticate(비밀번호) / cancel을 보낸다.
# 창은 rofi/polkit.rasi (런처와 같은 btop 상자). 비밀번호는 파이프로만 오가고 명령줄 인자에는 넣지 않는다.
# 요청 하나가 끝날 때까지 cmd-polkit(-s)은 다음 요청을 기다리게 하므로, 어떤 경우에도 답(cancel)을 보내고 EOF까지 남는다.
import html
import json
import os
import pwd
import select
import signal
import struct
import subprocess
import sys
import time

THEME = os.path.expanduser("~/.config/polybar/miniblocks/scripts/rofi/polkit.rasi")
# 런처·알림 센터와 다른 pid 파일 → 다른 rofi가 열려 있어도 "Rofi already running?"으로 막히지 않음
PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "rofi-polkit.pid")
# 맞는 비밀번호는 바로 끝나고, 틀리면 pam_unix가 2초(1~3초)를 끈다 → 이보다 오래 걸릴 때만 checking 줄을 띄움
CHECK_DELAY = 0.4
# PAM이 틀린 비밀번호에 거는 지연보다 빨리 온 거절 = 비밀번호 문제가 아님 (앱이 요청을 취소해 쿠키가 사라진 경우)
FAST_FAIL = 0.8
GRAB_TRIES = 6          # 다른 프로그램이 키보드를 잡고 있으면 0.5초 간격으로 다시 띄움

BOX, DIM, ERR, INFO, AC = "#ECEFF4", "#6c7984", "#BF616A", "#EBCB8B", "#ECEFF4"
USER = pwd.getpwuid(os.getuid()).pw_name

rofi = None             # 지금 떠 있는 rofi (신호로 끝날 때 같이 닫음)
buf = b""


def send(obj):
    try:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()
    except OSError:
        pass


def read_msg(timeout=None):
    """stdin에서 JSON 한 줄. 시간 초과면 None, EOF면 False"""
    global buf
    deadline = None if timeout is None else time.monotonic() + timeout
    while b"\n" not in buf:
        left = None if deadline is None else max(0.0, deadline - time.monotonic())
        if not select.select([0], [], [], left)[0]:
            return None
        chunk = os.read(0, 4096)
        if not chunk:
            return False
        buf += chunk
    line, buf = buf.split(b"\n", 1)
    try:
        msg = json.loads(line)
    except ValueError:
        return {}
    return msg if isinstance(msg, dict) else {}


def faillock():
    """(남은 횟수, 잠기는 시간 초). /run/faillock/<user>는 본인이 읽을 수 있다. 못 읽으면 None"""
    conf = {"dir": "/var/run/faillock", "deny": "3", "fail_interval": "900", "unlock_time": "600"}
    try:
        with open("/etc/security/faillock.conf", encoding="utf-8") as f:
            for line in f:
                key, eq, val = line.split("#", 1)[0].partition("=")
                if eq and key.strip() in conf:
                    conf[key.strip()] = val.strip()
        deny, interval, unlock = int(conf["deny"]), int(conf["fail_interval"]), int(conf["unlock_time"])
        with open(os.path.join(conf["dir"], USER), "rb") as f:
            data = f.read()
    except (OSError, ValueError):
        return None
    if deny <= 0:
        return None
    # struct tally { char source[52]; uint16_t reserved; uint16_t status; uint64_t time; } (Linux-PAM faillock.h)
    now = time.time()
    fails = sum(1 for _, _, status, t in struct.iter_unpack("=52sHHQ", data[:len(data) // 64 * 64])
                if status & 1 and now - t <= interval)
    return deny - fails, unlock


def lock_text(unlock):
    return f"a {round(unlock / 60)} min lock" if unlock > 0 else "the account locks"


def mesg(req, notes, wrong):
    """창 위쪽 글: 메시지, action id, 그리고 PAM 메시지나 틀림 안내 (pango markup)"""
    lines = [html.escape(req.get("message") or "Authentication is required.", quote=False)]
    act = req.get("polkit action")
    if isinstance(act, dict) and act.get("id"):
        lines += ["", f"<span color='{BOX}'>action</span>  "
                      f"<span color='{DIM}'>{html.escape(act['id'], quote=False)}</span>"]
    out = []
    for kind, text in notes:
        if kind == "err":
            out.append(f"<span color='{ERR}'>✗ {html.escape(text, quote=False)}</span>")
        else:
            out.append(f"<span color='{INFO}'>  {html.escape(text, quote=False)}</span>")
    # 잠김은 PAM(faillock)이 직접 알려 준다. 그 메시지가 없을 때만 우리 안내를 붙임
    if not any(kind == "err" for kind, _ in notes):
        fl = faillock()
        if wrong == "expired":
            out.append(f"<span color='{ERR}'>✗ request no longer valid, press esc to close</span>")
        elif wrong:
            left = ""
            if fl and fl[0] == 1:
                left = f", 1 try left before {lock_text(fl[1])}"
            elif fl and fl[0] > 1:
                left = f", {fl[0]} tries left"
            out.append(f"<span color='{ERR}'>✗ wrong password{left or ', try again'}</span>")
        elif fl and fl[0] == 1:
            out.append(f"<span color='{INFO}'>! 1 try left before {lock_text(fl[1])}</span>")
    if out:
        lines += [""] + out
    # rofi sizes -mesg at 17px per line (font metrics) but the font lays out taller lines,
    # so pin the line height or the last line gets clipped
    return "<span line_height='17408'>" + "\n".join(lines) + "</span>"


def prompt(req):
    p = (req.get("prompt") or "").strip().rstrip(":").strip()
    return f"password for {USER}" if not p or p.lower() == "password" else p


def start_rofi(req, notes, wrong, extra):
    args = ["rofi", "-dmenu", "-no-config", "-theme", THEME, "-pid", PIDFILE,
            "-p", prompt(req), "-mesg", mesg(req, notes, wrong), *extra]
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def close_rofi():
    global rofi
    if rofi is not None and rofi.poll() is None:
        rofi.terminate()
        try:
            rofi.wait(1)
        except subprocess.TimeoutExpired:
            rofi.kill()
            rofi.wait()
    rofi = None


def grab_failed(err):
    e = err.decode("utf-8", "replace").lower()
    return "grab" in e or "already running" in e


def give_up():
    subprocess.run(["notify-send", "-a", "polkit", "-u", "critical", "인증 창을 열지 못했습니다",
                    "다른 프로그램이 키보드를 잡고 있어 polkit 요청을 취소했습니다."], check=False)


def ask(req, notes, wrong):
    """비밀번호 창. 비밀번호 또는 취소면 None"""
    global rofi
    tries = 0
    while True:
        rofi = start_rofi(req, notes, wrong, ["-password"])
        out, err = rofi.communicate()
        rc, rofi = rofi.returncode, None
        if rc == 0:
            pw = out.decode("utf-8", "replace")
            pw = pw[:-1] if pw.endswith("\n") else pw
            if pw:
                return pw
            continue        # 빈 Enter: 빈 비밀번호도 faillock 실패로 세므로 보내지 않고 창을 다시 띄움
        if grab_failed(err):
            if tries < GRAB_TRIES:
                tries += 1
                time.sleep(0.5)
                continue
            give_up()
        return None


def checking_args(length):
    """show ********  checking… in place of the entry"""
    return ["-theme-str", "passbox { children: [ prompt, textbox-check ]; }",
            "-theme-str", f"textbox-check {{ content: \"{'*' * min(length, 40)}  "
                          f"<span color='{AC}'>checking…</span>\"; }}"]


def wait_result(req, length):
    """비밀번호를 보낸 뒤 다음 메시지를 기다린다. CHECK_DELAY가 지나면 checking 줄을 띄우고,
    거기서 Esc를 누르면 cancel을 보낸다. (다음 메시지 또는 EOF, 취소했는지)"""
    global rofi
    msg = read_msg(CHECK_DELAY)
    if msg is not None:
        return msg, False
    extra = checking_args(length)
    show = True
    while True:
        if show and rofi is None:
            rofi = start_rofi(req, [], False, extra)
        msg = read_msg(0.05)
        if msg is not None:
            close_rofi()
            return msg, False
        if rofi is None or rofi.poll() is None:
            continue
        rc, err = rofi.returncode, rofi.communicate()[1]
        rofi = None
        if grab_failed(err):
            show = False    # 확인 중 표시만 못 띄운 것: 결과는 계속 기다림
        elif rc != 0:
            send({"action": "cancel"})
            return None, True
        # Enter(rc 0)는 무시하고 다시 띄움


def main():
    notes, wrong, sent, cancelled, msg = [], False, None, False, None
    while True:
        if msg is None:
            msg = read_msg()
        if msg is False:
            return
        action, cur, msg = msg.get("action"), msg, None
        if action in ("show error", "show info"):
            text = str(cur.get("text") or "").strip()
            if text:
                notes.append(("err" if action == "show error" else "info", text))
        elif action == "authorization response" and not cur.get("authorized"):
            wrong = "expired" if sent is not None and time.monotonic() - sent < FAST_FAIL else True
        elif action == "request password" and not cancelled:
            pw = ask(cur, notes, wrong)
            notes, wrong = [], False
            if pw is None:
                send({"action": "cancel"})
                cancelled = True
                continue
            send({"action": "authenticate", "password": pw})
            sent, length = time.monotonic(), len(pw)
            del pw
            msg, cancelled = wait_result(cur, length)
            if msg is None and not cancelled:
                msg = read_msg()


def on_signal(signum, frame):
    close_rofi()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGHUP, on_signal)
    try:
        main()
    except Exception as e:
        # 답을 못 하면 cmd-polkit이 이 요청에서 멈추고 다음 요청도 막힌다 → 취소를 보내고 끝날 때까지 기다림
        print(f"polkit-rofi: {e!r}", file=sys.stderr)
        close_rofi()
        send({"action": "cancel"})
        while read_msg() is not False:
            pass
    finally:
        close_rofi()
