#!/usr/bin/env bash

# Volume / brightness / power profile OSD (eww window osd, ~/.config/eww; fade-in = picom 'Eww - osd' rule)
#   osd.sh Volume|Brightness <percent> [muted]   (volume.sh, dwm brightness keys)
#   osd.sh Profile quiet|balanced|performance    (osd-profile.sh on asusd profile changes)
# Icons are UTF-8 byte escapes so the script works in any locale.

case ${1,,} in
profile)
	case $2 in
	quiet) icon=$'\xF3\xB0\x8C\xAA' ;;
	balanced) icon=$'\xEF\x80\x93' ;;
	*) icon=$'\xEE\xBE\xA7' ;;
	esac
	eww update osd_kind=profile osd_icon="$icon" osd_title=Profile osd_value= osd_state= osd_profile="$2"
	;;
*)
	if [ "${1,,}" = volume ]; then
		icon=$'\xF3\xB0\x95\xBE'
		[ "$3" = muted ] && icon=$'\xF3\xB0\x96\x81'
		title=Volume
	else
		icon=$'\xF3\xB0\x83\xA0'
		title=Brightness
	fi
	if [ "$3" = muted ]; then
		value=Muted state=muted
	else
		value="$2%" state=
	fi
	eww update osd_kind="${1,,}" osd_icon="$icon" osd_title="$title" osd_value="$value" osd_pct="$2" osd_state="$state"
	;;
esac

# Already open: only the content changes (re-opening recreates the window and repeats the fade-in)
eww active-windows | grep -q '^osd:' || eww open osd

# Close 1.5 s after the last call; earlier timers see a newer stamp and do nothing
stamp=${XDG_RUNTIME_DIR:-/tmp}/eww-osd.stamp
echo $$ > "$stamp"
(sleep 1.5; [ "$(cat "$stamp" 2>/dev/null)" = $$ ] && eww close osd) >/dev/null 2>&1 &
