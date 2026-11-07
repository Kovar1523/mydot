# kitty 데스크톱 알림 한글화
# kitty는 알림을 보내기 직전에 main(cmd)를 부름. True를 돌려주면 알림을 버리고, False면 그대로 보냄.
# 여기서는 cmd.body를 한글로 바꾸고 항상 False를 돌려줌 → dunst에는 한글 문구가 도착함.
# kitty 시작 시 한 번만 읽히므로, 고친 뒤에는 새로 연 kitty 창부터 적용됨.
# 새 문구 추가: dunstctl history로 원문을 확인한 뒤 RULES에 (정규식, 바꿀 문구) 추가

import re

# Dropped: only task finished/failed alerts are shown
DROP = [
    r'Claude is waiting for your input',
    r'Claude needs your permission.*',
]
DROP = [re.compile(pat, re.DOTALL) for pat in DROP]

RULES = [
    # 백그라운드 작업: "<작업명> finished" / "<작업명> failed"
    (r'(.+) finished', r'\1 작업이 끝났어요'),
    (r'(.+) failed', r'\1 작업이 실패했어요'),
]
RULES = [(re.compile(pat, re.DOTALL), repl) for pat, repl in RULES]


def main(nc) -> bool:
    if any(pat.fullmatch(nc.body) for pat in DROP):
        return True
    for pat, repl in RULES:
        if m := pat.fullmatch(nc.body):
            nc.body = m.expand(repl)
            break
    return False
