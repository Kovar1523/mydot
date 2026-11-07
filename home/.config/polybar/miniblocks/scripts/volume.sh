#!/usr/bin/env bash

# Volume control for the pulseaudio module (PipeWire via wpctl).
#   up     : +5% (max 100%), unmutes if it was auto-muted at 0%
#   down   : -5%, mutes automatically when it reaches 0%
#   toggle : toggle mute

SINK="@DEFAULT_AUDIO_SINK@"
STEP="5%"

# "Volume: 0.40" or "Volume: 0.00 [MUTED]"
read -r _ vol muted <<< "$(wpctl get-volume "$SINK")"

case "$1" in
	up)
		if [ -n "$muted" ] && awk -v v="$vol" 'BEGIN { exit !(v == 0) }'; then
			wpctl set-mute "$SINK" 0
		fi
		wpctl set-volume -l 1.0 "$SINK" "$STEP+"
		;;
	down)
		wpctl set-volume "$SINK" "$STEP-"
		read -r _ vol _ <<< "$(wpctl get-volume "$SINK")"
		if awk -v v="$vol" 'BEGIN { exit !(v == 0) }'; then
			wpctl set-mute "$SINK" 1
		fi
		;;
	toggle)
		wpctl set-mute "$SINK" toggle
		;;
	*)
		echo "Usage: $0 up|down|toggle" >&2
		exit 1
		;;
esac

# TUI popup (~/.config/dunst/osd.sh): keys and the polybar wheel both end up here
read -r _ vol muted <<< "$(wpctl get-volume "$SINK")"
~/.config/dunst/osd.sh Volume "$(awk -v v="$vol" 'BEGIN { printf "%d", v * 100 + 0.5 }')" ${muted:+muted}
