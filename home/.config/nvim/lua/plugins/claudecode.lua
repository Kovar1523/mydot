return {
  {
    "coder/claudecode.nvim",
    dependencies = { "folke/snacks.nvim" },
    opts = {
      terminal = {
        provider = "snacks",
        snacks_win_opts = {
          position = "bottom",
          height = 0.3, -- 화면 높이의 30%
        },
      },
    },
    keys = {
      { "<leader>ac", "<cmd>ClaudeCode<cr>",     desc = "Toggle Claude" },
      { "<leader>as", "<cmd>ClaudeCodeSend<cr>", mode = "v",            desc = "Send to Claude" },
    },
  },
}
