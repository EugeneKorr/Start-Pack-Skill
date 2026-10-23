#!/usr/bin/env bash
# Журнал прогонов агента: текст со stdin дописывается в ~/.claude/ticket-agent/runs/<ГГГГ-ММ-ДД>.md.
# Агент не может писать в ~/.claude напрямую (защищённый каталог Claude Code), поэтому — через этот скрипт.
set -euo pipefail
RUNS="$HOME/.claude/ticket-agent/runs"
mkdir -p "$RUNS"
{ cat; echo; } >> "$RUNS/$(date +%Y-%m-%d).md"
