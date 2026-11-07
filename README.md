# dotfiles

Arch Linux · X11 · dwm · ASUS FA608UM (AMD 780M + NVIDIA) 환경 스냅샷 (2026-11-07).

## 구성

| 경로 | 내용 | 원래 위치 |
|---|---|---|
| `home/` | 사용자 설정 | `~/` 그대로 (예: `home/.config/kitty` → `~/.config/kitty`) |
| `dwm/` | 패치된 dwm 소스 (`config.h` 포함) | `~/dwm` |
| `dwm-patches/local.diff` | upstream `bca7cf2` 대비 현재 수정 전체 | |
| `dwm-patches/tag-unmap.diff` | tag-unmap worktree 버전 (설치 전) | `~/dwm/.claude/worktrees/tag-unmap` |
| `system/` | root 권한 파일 | `/` 기준 (예: `system/etc/asusd` → `/etc/asusd`) |
| `system/boot-staged/` | Limine/콘솔 폰트 준비본 (아직 미적용) | `~/bootfont` |
| `packages/pacman.txt` | 공식 저장소 명시 설치 패키지 | `pacman -Qqen` |
| `packages/aur.txt` | AUR 패키지 | `pacman -Qqem` |

## 주요 구성 요소

- WM: dwm (`.xinitrc` → `startx`, tty1 로그인)
- 바: polybar `miniblocks` (`~/.config/polybar/miniblocks`)
- 컴포지터: picom (raven2cz 기반)
- 런처/메뉴: rofi (adi1090x launcher, Dock powermenu, Hack 메뉴)
- 알림/OSD: dunst, eww
- 터미널: kitty (JetBrainsMono Nerd Font Mono + Pretendard)
- 색상: pywal16 (`~/.config/wal/apply.sh` + templates)
- 입력기: fcitx5-hangul
- 배경: xwinwrap + mpv (`usercustom/aurora-2240x1400.mp4`)

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
