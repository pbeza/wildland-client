sudo apt install -y tmux xclip
git clone https://github.com/gpakosz/.tmux.git $HOME/oh-my-tmux && \
ln -s -f $HOME/oh-my-tmux/.tmux.conf $HOME/ && \
cp $HOME/oh-my-tmux/.tmux.conf.local $HOME/ && \
cat << EOF >> $HOME/.tmux.conf.local
bind-key    -T copy-mode    C-w               send-keys -X copy-selection
bind-key    -T copy-mode    MouseDragEnd1Pane send-keys -X copy-selection
bind-key    -T copy-mode    M-w               send-keys -X copy-selection
bind-key    -T copy-mode-vi C-j               send-keys -X copy-selection
bind-key    -T copy-mode-vi Enter             send-keys -X copy-selection
bind-key    -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-selection
bind-key C-g new-window "gotty --permit-write --random-url --port 0 tmux attach -t \`tmux display -p '#S'\`"
bind C-s set-window-option synchronize-panes
set -g mouse on
EOF