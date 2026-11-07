-- Options are automatically loaded before lazy.nvim startup
-- Default options that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/options.lua
-- Add any additional options here
vim.g.clipboard = {
  name = "clipcat",
  copy = {
    ["+"] = { "clipcatctl", "load" },
    ["*"] = { "clipcatctl", "load", "-k", "primary" },
  },
  paste = {
    ["+"] = { "clipcatctl", "save" },
    ["*"] = { "clipcatctl", "save", "-k", "primary" },
  },
  cache_enabled = 0,
}

-- 순정 Vim 스타일 줄 표시
vim.opt.relativenumber = false          -- 절대 줄 번호만
vim.opt.signcolumn = "no"               -- 왼쪽 아이콘 열(진단·git) 없애기
vim.opt.statuscolumn = ""               -- LazyVim 전용 줄 열(접기·git 표시) 끄기
vim.opt.fillchars:append({ eob = "~" }) -- 파일 끝 다음 줄을 ~ 로
