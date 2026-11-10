# dotfiles

Arch Linux · X11 · dwm · ASUS FA608UM (AMD 780M + NVIDIA) 환경 스냅샷 (2026-11-10).

## 구성

| 경로 | 내용 | 원래 위치 |
|---|---|---|
| `home/` | 사용자 설정 | `~/` 그대로 (예: `home/.config/kitty` → `~/.config/kitty`) |
| `dwm/` | 패치된 dwm 소스 (`config.h` 포함) | `~/dwm` |
| `dwm-patches/local.diff` | upstream `bca7cf2` 대비 현재 수정 전체 | |
| `system/` | root 권한 파일 | `/` 기준 (예: `system/etc/asusd` → `/etc/asusd`) |
| `system/boot-staged/` | Limine/콘솔 폰트 준비본 (아직 미적용) | `~/bootfont` |
| `packages/pacman.txt` | 공식 저장소 명시 설치 패키지 | `pacman -Qqen` |
| `packages/aur.txt` | AUR 패키지 | `pacman -Qqem` |

## 주요 구성 요소

- WM: dwm (`.xinitrc` → `startx`, tty1 로그인)
- 바: polybar `miniblocks` (`~/.config/polybar/miniblocks`)
- 컴포지터: picom (raven2cz 기반)
- 런처/메뉴: rofi (adi1090x launcher, Dock powermenu, Hack 메뉴)
- 알림/OSD: dunst, eww (OSD + 알림 센터 `notifcenter.yuck`)
- 터미널: kitty (JetBrainsMono Nerd Font Mono + Pretendard)
- 색상: pywal16 (`~/.config/wal/apply.sh` + templates)
- 입력기: fcitx5-hangul
- 배경: xwinwrap (AUR `xwinwrap-git`) + mpv (`usercustom/wavy-grass-moewalls-com.mp4`, 옵션은 `mpv.conf`의 `[wallpaper]` 프로필)

## 색상 팔레트

pywal16이 `home/Downloads/aurora-wallpaper.png`에서 뽑은 팔레트입니다. 원본 이미지는 `~/Downloads`에서 지워져 이 저장소에만 남아 있습니다.

- 생성된 결과: `home/.cache/wal/` (`colors.json`, `sequences`, `colors-tty.sh`, `dunst.conf`, `colors-rofi.rasi`, `colors-polybar.ini`, `btopwal.theme` 등)
- 템플릿과 적용 스크립트: `home/.config/wal/` (`apply.sh`, `templates/`, `colorschemes/dark/nord.json`)

| 키 | 값 |
|---|---|
| background / color0 | `#0c161d` |
| foreground / color7 / color15 | `#c2c4c6` |
| color1 / 9 | `#128590` |
| color2 / 10 | `#127ebb` |
| color3 / 11 | `#0F9073` |
| color4 / 12 | `#226eff` |
| color5 / 13 | `#1379d6` |
| color6 / 14 | `#0e7dc5` |
| color8 | `#6c7984` |

다시 생성하려면 이미지를 `~/Downloads`에 복사한 뒤 `wal -i ~/Downloads/aurora-wallpaper.png`, 이어서 `~/.config/wal/apply.sh`.

## 셸

- `home/.bashrc`: eza alias(`ls`/`ll`/`la`/`lt`), `EDITOR=nvim`, starship, fzf 색상, X 안에서 fastfetch
- `home/.bash_profile`: tty1 로그인 시 fastfetch를 한 줄씩 출력한 뒤 `startx`
- `home/.config/starship.toml`: 프롬프트
- `home/.config/fastfetch/config.jsonc`: pfetch 스타일, 인라인 로고
- `home/.config/eza/theme.yml`: eza 색상

## 복원

```
sudo pacman -S --needed - < packages/pacman.txt
yay -S --needed - < packages/aur.txt
rsync -a home/ ~/
cd dwm
make
sudo make install
```

`system/` 파일은 하나씩 확인 후 `sudo cp`로 넣으세요.

## 제외한 것

- `.before-*` / `.bak` 백업, 예전 polybar 테마(`hack`, `shades`)
- Firefox 프로필 (chrome/와 user.js만 포함), Discord, Notion, Steam, 게임 설정
- 키링·토큰·히스토리, `~/.claude`의 settings.json 외 전부
- uosc의 Windows/macOS 바이너리

## 참고

- `home/.config/dunst/dunstrc.d/50-wal.conf`는 `~/.cache/wal/dunst.conf` 링크입니다. wal을 한 번 실행해야 생깁니다.
- `/boot/limine.conf`는 읽기 권한이 없어 포함하지 않았습니다.
