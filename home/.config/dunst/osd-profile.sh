#!/usr/bin/env bash

# 전원 프로필이 바뀌면 (Fn+F5, asusctl profile, 전원 연결에 따른 자동 전환) osd.sh로 btop 스타일 팝업을 띄움
# Fn+F5는 X까지 오지 않고 커널(asus-wmi)이 직접 프로필을 바꿈 → asusd가 알아채고 DBus로 알리는 것을 받음
# 충전기 연결/분리로 바뀐 경우는 dunst 알림도 띄움: asusd는 ACAD/online이 바뀐 다음 프로필을 다시 쓰므로
# 신호가 왔을 때 ACAD/online이 직전 값과 다르면 전원 전환 때문 (asusd는 한 번에 신호를 두 번 보냄 → 첫 번째에서만 알림)
# 세션 시작 3초 뒤 GPU 모드와 프로필을 dunst로 한 번 알림 (picom이 뜬 다음이라 반투명·애니메이션 적용)
# .xinitrc에서 실행. flock으로 하나만 실행: 로그아웃 뒤 남은 것이 있으면 새로 띄우지 않고 그것이 계속 처리
# 시작 알림은 flock 앞이라 남은 것이 있어도 뜸

ac=/sys/class/power_supply/ACAD/online
profile=/sys/firmware/acpi/platform_profile
gpu=/sys/class/firmware-attributes/asus-armoury/attributes

# osd.sh와 같은 아이콘(UTF-8 바이트)·색
declare -A icons=([quiet]=$'\xF3\xB0\x8C\xAA' [balanced]=$'\xEF\x80\x93' [performance]=$'\xEE\xBE\xA7')
declare -A colors=([quiet]='#A3BE8C' [balanced]='#88C0D0' [performance]='#D08770') # nord14 / nord8 / nord12

# notify <ACAD/online> <이전 프로필> <새 프로필>: 오른쪽 위 dunst 알림, 테두리는 새 프로필 색
# 아이콘은 위 글리프를 같은 폰트로 그린 SVG (dunst 아이콘 자리는 이미지만 받음): icons/profile-<프로필>.svg
# stack-tag: 충전기를 연달아 꽂았다 빼도 알림이 쌓이지 않고 하나가 바뀜. 기록 제외는 dunstrc [power_profile]
notify() {
	local summary='충전기 분리됨' body
	local new="<span foreground=\"${colors[$3]}\" weight=\"bold\">${icons[$3]} $3</span>"
	[ "$1" = 1 ] && summary='충전기 연결됨'
	if [ "$2" = "$3" ]; then body="프로필 $new 유지"; else body="프로필 $2 → $new"; fi
	notify-send -a power-profile -u low -i ~/.config/dunst/icons/profile-"$3".svg \
		-h string:x-dunst-stack-tag:power-profile -h "string:frcolor:${colors[$3]}" "$summary" "$body"
}

# status: 세션 시작 알림. MUX 0 = Ultimate, MUX 1 + dGPU 꺼짐 = Eco, 나머지 Hybrid
status() {
	local p=$(< $profile) mode='Hybrid (iGPU + dGPU)'
	if [ "$(< $gpu/gpu_mux_mode/current_value)" = 0 ]; then mode='Ultimate (dGPU 전용)'
	elif [ "$(< $gpu/dgpu_disable/current_value)" = 1 ]; then mode='Eco (iGPU 전용)'
	fi
	notify-send -a power-profile -u low -i ~/.config/dunst/icons/profile-"$p".svg \
		-h "string:frcolor:${colors[$p]}" '시스템 상태' \
		"GPU    $mode"$'\n'"프로필 <span foreground=\"${colors[$p]}\" weight=\"bold\">${icons[$p]} $p</span>"
}

(sleep 3; status) &

exec 9> "${XDG_RUNTIME_DIR:-/tmp}/osd-profile.lock"
flock -n 9 || exit 0

last_ac=$(< $ac) last=$(< $profile)

gdbus monitor --system --dest xyz.ljones.Asusd --object-path /xyz/ljones |
	while read -r line; do
		# PlatformProfileOnAc 같은 비슷한 이름의 다른 속성은 제외: {'PlatformProfile': <uint32 n>}
		# 9>&-: osd.sh가 eww 데몬을 새로 띄우는 경우 데몬이 잠금을 물려받지 않게
		case $line in
		*"'PlatformProfile': <"*)
			now=$(< $profile) now_ac=$(< $ac)
			if [ "$now_ac" != "$last_ac" ]; then
				notify "$now_ac" "$last" "$now"
				last_ac=$now_ac
			fi
			last=$now
			~/.config/dunst/osd.sh Profile "$now" 9>&-
			;;
		esac
	done
