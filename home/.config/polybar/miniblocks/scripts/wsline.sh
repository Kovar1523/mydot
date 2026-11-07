#!/usr/bin/env bash
# polybar 태그 밑줄 슬라이드 애니메이션 (config.ini [module/wsline], tail = true)
# - [module/workspaces] 바로 뒤에서 음수 오프셋으로 되돌아가 밑줄만 그림 → 이 모듈의 폭은 0
# - 태그 글자·클릭·휠·점유 표시는 workspaces 모듈(internal/xworkspaces)이 그대로 처리
# - dwm이 바꾸는 _NET_CURRENT_DESKTOP을 xprop -spy로 기다림 → 평소 CPU 사용 0
# - 밑줄 색은 config.ini의 format-underline (= colors.highlight)

cell=8               # font cell width: JetBrainsMono Nerd Font Mono 14px = 8px
tags=(I II III IV V) # workspaces 모듈의 icon-0 ~ icon-4와 같게
pad=1                # label-*-padding (칸)
frames=10            # 프레임 수
step=0.016           # 프레임 간격(초): 10 × 16ms = 160ms

# 태그별 밑줄 시작 x·폭 (workspaces 모듈 왼쪽 끝 기준 px)
xs=() ws=() total=0
for t in "${tags[@]}"; do
	w=$(( (${#t} + 2 * pad) * cell ))
	xs+=("$total"); ws+=("$w"); total=$(( total + w ))
done

# $1 = x, $2 = 폭: 모듈 끝에서 total만큼 되돌아가 x만큼 건너뛰고, 폭만큼 밑줄, 나머지만큼 다시 앞으로
draw() {
	printf '%%{-u}%%{O%d}%%{+u}%%{O%d}%%{-u}%%{O%d}\n' $(( $1 - total )) "$2" $(( total - $1 - $2 ))
}

exec 3< <(exec xprop -root -spy _NET_CURRENT_DESKTOP)
xp=$!
trap 'kill "$xp" 2>/dev/null' EXIT
trap 'exit 0' TERM INT HUP

cx=-1 cw=0 tx=-1 tw=0 i=0 n=0
while :; do
	# 움직이는 중이면 한 프레임만큼만 기다리고, 아니면 다음 태그 이동까지 기다림
	if (( n )); then read -r -t "$step" line <&3; rc=$?; else read -r line <&3; rc=$?; fi
	if (( rc == 0 )); then
		[[ $line =~ =\ ([0-9]+) ]] || continue
		d=${BASH_REMATCH[1]}
		(( d < ${#tags[@]} )) || continue
		# 이미 그 태그로 가는 중이거나 도착함
		(( xs[d] == tx && ws[d] == tw )) && continue
		tx=${xs[d]} tw=${ws[d]}
		# 처음 한 번은 바로 그림
		if (( cx < 0 )); then cx=$tx cw=$tw; draw "$cx" "$cw"; continue; fi
		# 지금 밑줄 자리(움직이는 중이면 그 자리)에서 새로 출발
		sx=$cx sw=$cw i=0 n=$frames
	elif (( rc <= 128 )); then
		exit 0 # xprop 종료
	fi
	(( n )) || continue
	# ease-out cubic: e = 1 - (1 - t)^3 (0~1000)
	i=$(( i + 1 )); q=$(( 1000 - i * 1000 / n )); e=$(( 1000 - q * q * q / 1000000 ))
	cx=$(( sx + (tx - sx) * e / 1000 )) cw=$(( sw + (tw - sw) * e / 1000 ))
	draw "$cx" "$cw"
	(( i < n )) || n=0
done
