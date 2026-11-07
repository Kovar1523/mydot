#!/usr/bin/env bash
# 이미지에서 16색을 뽑아 polybar · rofi · dunst · kitty 에 적용
# 사용법: ~/.config/wal/apply.sh 이미지     (이미지 없이 실행하면 마지막 이미지로 다시 적용)
# 템플릿: ~/.config/wal/templates/ → ~/.cache/wal/
# -n 배경화면 안 바꿈(xwinwrap 영상 유지)  -s -t 터미널/TTY 색 시퀀스 안 보냄(kitty #000000 유지)  -e xrdb 등 안 건드림

contrast=3.5

if [[ -n $1 ]]; then src=(-i "$1"); else src=(-w); fi
wal -n -s -t -e -q --contrast "$contrast" "${src[@]}" || exit 1

# 색 칸 배치 (11-05): 열 순서 = 검정/회색, 흰색, 파랑 → 청록 → 초록 → 주황 → 빨강 (1줄 0~7, 2줄 8~15 같은 열)
# 새 색은 넣지 않음: 0 검정 · 8 회색 · 1·9 흰색(color7) = 배경화면 색, 나머지 = 배경화면 color1~4 + 주황 #d08770 · 빨강 #bf616a
python3 - <<'PY' || exit 1
import colorsys, json, os
d = os.path.expanduser('~/.cache/wal/')
j = json.load(open(d + 'colors.json'))
c = j['colors']
def rgb(h):
    return [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
def hue(h):
    x = colorsys.rgb_to_hsv(*rgb(h))[0] * 360
    return x - 360 if x >= 330 else x   # 자홍~빨강 끝(330° 이상)은 빨강 쪽
pool = [c[f'color{i}'] for i in range(1, 5)] + ['#d08770', '#bf616a']
pool.sort(key=hue, reverse=True)
c['color1'] = c['color9'] = c['color7']
for i, h in enumerate(pool, 2):
    c[f'color{i}'] = c[f'color{i + 8}'] = h
json.dump(j, open(d + 'colors-accent.json', 'w'), indent=4)
PY
wal -n -s -t -e -q -f ~/.cache/wal/colors-accent.json || exit 1

polybar-msg cmd restart >/dev/null
dunstctl reload
pkill -USR1 -x kitty
