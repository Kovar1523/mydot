#!/bin/sh
# Polybar reader for one barsd.py output: barsd-read.sh <music|notif>
dir="${XDG_RUNTIME_DIR:-/tmp}/barsd"
mkdir -p "$dir"
[ -p "$dir/$1" ] || mkfifo "$dir/$1" 2>/dev/null
# Read-write open: never blocks and keeps the pipe while barsd.py restarts
exec cat 0<>"$dir/$1"
