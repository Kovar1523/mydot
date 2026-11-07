#!/usr/bin/env bash

## Author  : Aditya Shakya
## Mail    : adi1090x@gmail.com
## Github  : @adi1090x
## Twitter : @adi1090x

dir="$HOME/.config/rofi/applets/menu"
rofi_command="rofi -theme $dir/quicklinks_square.rasi"

# Icons (Nerd Font)
firefox=$'\U000f0239'
reddit=$'\uf1a1'
github=$'\U000f02a4'
discord=$'\U000f066f'
youtube=$'\U000f05c3'

options="$firefox\n$reddit\n$github\n$discord\n$youtube"

chosen="$(echo -e "$options" | $rofi_command -dmenu -selected-row 0)"
case $chosen in
    $firefox)
        firefox &
        ;;
    $reddit)
        firefox https://www.reddit.com &
        ;;
    $github)
        firefox https://www.github.com &
        ;;
    $discord)
        discord &
        ;;
    $youtube)
        firefox https://www.youtube.com &
        ;;
esac
