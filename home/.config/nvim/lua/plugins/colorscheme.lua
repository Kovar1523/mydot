return {
  {
    "gbprod/nord.nvim",
    lazy = false,
    priority = 1000,
    opts = {
      transparent = true,
      -- transparent 는 Normal·SignColumn 만 투명하게 하므로
      -- 떠 있는 창·winbar(dropbar) 도 이전 tokyonight 설정처럼 투명하게
      on_highlights = function(highlights)
        for _, group in ipairs({ "NormalFloat", "FloatBorder", "FoldColumn", "WinBar", "WinBarNC" }) do
          if highlights[group] then
            highlights[group].bg = "NONE"
          end
        end
        -- 기본 주석색 #616E88 은 투명 배경에서 잘 안 보여서 더 밝은 회청색으로
        for _, group in ipairs({ "Comment", "@comment" }) do
          if highlights[group] then
            highlights[group].fg = "#8C9AB3"
          end
        end
      end,
    },
  },
  {
    "LazyVim/LazyVim",
    opts = {
      colorscheme = "nord",
    },
  },
}
