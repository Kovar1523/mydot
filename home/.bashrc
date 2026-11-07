#
# ~/.bashrc
#

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

alias ls='eza --icons=auto --group-directories-first'
alias ll='eza -l --git --icons=auto --group-directories-first'
alias la='eza -la --git --icons=auto --group-directories-first'
alias lt='eza --tree --level=2 --icons=auto'
alias grep='grep --color=auto'
PS1='[\u@\h \W]\$ '
export EDITOR=nvim
export VISUAL=nvim

eval "$(starship init bash)"

export PATH="$HOME/.local/bin:$PATH"
export FZF_DEFAULT_OPTS='--color=fg:-1,bg:-1,hl:6,fg+:15,bg+:0,hl+:14,gutter:-1,info:4,prompt:6,pointer:6,marker:2,spinner:5,header:4,border:8,separator:8,scrollbar:8,label:4,query:-1'
if [[ -n $DISPLAY ]]; then fastfetch; echo; fi
