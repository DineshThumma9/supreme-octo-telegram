#!/usr/bin/env bash
# Delegate to tmux launcher script
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/start-tmux.sh" "$@"
