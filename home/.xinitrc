export QT_QPA_PLATFORMTHEME=gtk3

if [ -d /etc/X11/xinit/xinitrc.d ]; then
  for f in /etc/X11/xinit/xinitrc.d/?*.sh; do
    [ -x "$f" ] && . "$f"
  done
  unset f
fi

dbus-update-activation-environment --systemd QT_QPA_PLATFORMTHEME

export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
export GLFW_IM_MODULE=ibus

xrdb -merge ~/.Xresources

if xrandr --query | grep -q '^DP-0 connected'; then
  xrandr --output DP-0 --mode 1920x1200 --rate 165
  nvidia-settings --no-write-config -a AllowFlipping=0 >/dev/null 2>&1
  export MOZ_DISABLE_RDD_SANDBOX=1
  export CUDA_DISABLE_PERF_BOOST=1
fi

fcitx5 -r -d &
xwinwrap -fs -ov -b -nf -ni -- mpv -wid %WID --no-config --really-quiet --loop-file=inf --no-audio --no-osc --hwdec=vaapi,nvdec --vo=gpu --gpu-api=opengl --profile=fast --panscan=1.0 ~/usercustom/aurora-2240x1400.mp4 &
PICOM_DEBUG=force_vblank_sched=present picom -b &
clipcatd &
cmd-polkit-agent -s -c ~/.config/polybar/miniblocks/scripts/polkit-rofi.py &
eww daemon &
~/.config/dunst/osd-profile.sh &
batsignal -w 30 -c 15 &
xscreensaver --no-splash &

systemd-inhibit --what=handle-power-key --who=dwm --why="dwm power menu" --mode=block dwm
