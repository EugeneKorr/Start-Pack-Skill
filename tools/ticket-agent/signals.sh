#!/usr/bin/env bash
# Входящие сигналы детектора для сборщика: signals.sh list | signals.sh done <файл>
set -euo pipefail
INBOX="$HOME/.claude/ticket-agent/inbox"
case "${1:-}" in
  list)
    shopt -s nullglob
    for f in "$INBOX"/*.json; do echo "== $f"; cat "$f"; echo; done ;;
  done)
    case "${2:-}" in "$INBOX"/*.json) ;; *) echo "только файлы из $INBOX" >&2; exit 2 ;; esac
    mkdir -p "$INBOX/done"; mv "$2" "$INBOX/done/" ;;
  *) echo "usage: signals.sh list | done <файл>" >&2; exit 2 ;;
esac
