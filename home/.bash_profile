#
# ~/.bash_profile
#

[[ -f ~/.bashrc ]] && . ~/.bashrc

if [ -z "$DISPLAY" ] && [ "$XDG_VTNR" = 1 ]; then
  fastfetch --pipe false | while IFS= read -r line || [ -n "$line" ]; do printf '%s\n' "$line"; sleep 0.05; done
  sleep 1
  exec startx
fi
