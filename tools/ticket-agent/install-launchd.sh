#!/usr/bin/env bash
# Установка ядра агента «тикет → фикс» на Мак: каталоги, конфиг, реестр, launchd.
# install-launchd.sh install | uninstall
set -euo pipefail
DIR="$HOME/.claude/ticket-agent"
TOOLS="$HOME/.claude/tools/ticket-agent"
LA="$HOME/Library/LaunchAgents"
UIDN=$(id -u)
CLAUDE_BIN_DIR=$(dirname "$(command -v claude)")
PATH_LINE="$CLAUDE_BIN_DIR:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin"

plist() { # label schedule-xml program [args...]
  local label="$1" sched="$2"; shift 2
  local args=""
  for a in "$@"; do args="$args<string>$a</string>"; done
  cat > "$LA/$label.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key><array>$args</array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$PATH_LINE</string></dict>
  $sched
  <key>StandardOutPath</key><string>$DIR/runs/launchd.log</string>
  <key>StandardErrorPath</key><string>$DIR/runs/launchd.log</string>
</dict></plist>
EOF
}
at() { echo "<dict><key>Hour</key><integer>$1</integer><key>Minute</key><integer>$2</integer></dict>"; }

LABELS="com.vladimir.ticket-agent.watch com.vladimir.ticket-agent.collect com.vladimir.ticket-agent.fix com.vladimir.ticket-agent.digest"

case "${1:-}" in
  install)
    mkdir -p "$DIR/runs" "$DIR/inbox" "$DIR/projects" "$LA"
    [ -f "$DIR/config.json" ] || cp "$TOOLS/config.example.json" "$DIR/config.json"
    [ -f "$DIR/state.json" ] || echo '{}' > "$DIR/state.json"
    [ -f "$DIR/projects/vega.json" ] || cp "$TOOLS/vega.project.example.json" "$DIR/projects/vega.json"
    plist com.vladimir.ticket-agent.watch   "<key>StartInterval</key><integer>300</integer>" /usr/bin/python3 -I "$TOOLS/watch.py"
    plist com.vladimir.ticket-agent.collect "<key>StartCalendarInterval</key><array>$(at 9 0)$(at 14 0)$(at 19 0)</array>" "$TOOLS/run.sh" collect
    plist com.vladimir.ticket-agent.digest  "<key>StartCalendarInterval</key><array>$(at 7 30)</array>" "$TOOLS/run.sh" digest
    # Отдельного ночного фикса нет (26.10): фиксер запускается из run.sh после каждого сбора.
    launchctl bootout "gui/$UIDN/com.vladimir.ticket-agent.fix" 2>/dev/null || true
    rm -f "$LA/com.vladimir.ticket-agent.fix.plist"
    for l in $LABELS; do
      [ "$l" = "com.vladimir.ticket-agent.fix" ] && continue
      launchctl bootout "gui/$UIDN/$l" 2>/dev/null || true
      launchctl bootstrap "gui/$UIDN" "$LA/$l.plist"
    done
    echo "Установлено. Включить: \"enabled\": true в $DIR/config.json." ;;
  uninstall)
    for l in $LABELS; do
      launchctl bootout "gui/$UIDN/$l" 2>/dev/null || true
      rm -f "$LA/$l.plist"
    done
    echo "launchd-задания сняты; $DIR сохранён." ;;
  *) echo "usage: install-launchd.sh install|uninstall" >&2; exit 2 ;;
esac
