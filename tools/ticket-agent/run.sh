#!/usr/bin/env bash
# Безлюдный запуск роли агента «тикет → фикс» (ядро): collect | fix | digest [--p0] [--dry].
# Спек: Start-Pack-Skill/docs/specs/2026-10-23-ticket-agent-core.md
set -euo pipefail

ROLE="${1:-}"; shift || true
EXTRA="$*"
DIR="$HOME/.claude/ticket-agent"
TOOLS="$HOME/.claude/tools/ticket-agent"
CFG="$DIR/config.json"

[ -f "$CFG" ] || exit 0
python3 -I -c 'import json,sys;sys.exit(0 if json.load(open(sys.argv[1])).get("enabled") else 1)' "$CFG" || exit 0

case "$ROLE" in
  collect) MODEL=sonnet ;;
  fix)     MODEL=opus ;;
  digest)  MODEL=sonnet ;;
  *) echo "usage: run.sh collect|fix|digest [--p0] [--dry]" >&2; exit 2 ;;
esac

mkdir -p "$DIR/runs"
LOG="$DIR/runs/$(date +%Y-%m-%d).log"

# Реестр: проверка и всё, что из него нужно запуску. Ошибка — в журнал прогонов (её увидит сводка).
# Печатает: 1-я строка — fix_ok (1/0), 2-я — worktrees_dir, дальше — пути репо включённых проектов.
if ! REG=$(python3 -I - "$DIR" 2>&1 <<'PY'
import glob, json, sys
d = sys.argv[1]
cfg = json.load(open(f"{d}/config.json"))
repos, fix_ok = [], False
for f in sorted(glob.glob(f"{d}/projects/*.json")):
    try:
        p = json.load(open(f))
        if not p.get("enabled"):
            continue
        fix_ok = fix_ok or bool(p.get("fix_enabled"))
        repos += [r["path"] for r in p["repos"]]
    except Exception as e:
        sys.exit(f"реестр {f}: {e}")
print(1 if fix_ok else 0)
print(cfg["worktrees_dir"])
print("\n".join(repos))
PY
); then
  echo "!!! $(date '+%F %T') $ROLE: $REG" >> "$LOG"
  exit 1
fi
FIX_OK=$(echo "$REG" | sed -n 1p)
WORKTREES=$(echo "$REG" | sed -n 2p)
REPOS=()
while IFS= read -r line; do [ -n "$line" ] && REPOS+=("$line"); done < <(echo "$REG" | sed -n '3,$p')
# Нет включённых проектов — делать нечего (и bash 3.2 с set -u падает на пустом массиве).
[ "${#REPOS[@]}" -gt 0 ] || exit 0

# Фиксер не запускаем, если ни у одного проекта не включён fix_enabled.
if [ "$ROLE" = "fix" ] && [ "$FIX_OK" != "1" ]; then exit 0; fi

# Один прогон за раз (общая блокировка с watch.py). Старше 3 часов — прогон умер, снимаем.
LOCKDIR="$DIR/run.lock"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  age=$(( $(date +%s) - $(stat -f %m "$LOCKDIR") ))
  if [ "$age" -gt 10800 ]; then rmdir "$LOCKDIR"; mkdir "$LOCKDIR"; else exit 0; fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

mkdir -p "$WORKTREES"
echo "=== $(date '+%F %T') $ROLE $EXTRA" >> "$LOG"

# Настройки прогона: базовые + запрет Edit/Write в рабочих деревьях репо (агент правит только worktree).
GEN="$DIR/settings.generated.json"
python3 -I - "$TOOLS/settings.json" "$GEN" "${REPOS[@]}" <<'PY'
import json, sys
base, out, repos = sys.argv[1], sys.argv[2], sys.argv[3:]
s = json.load(open(base))
for r in repos:
    s["permissions"]["deny"] += [f"Edit(/{r}/**)", f"Write(/{r}/**)"]
json.dump(s, open(out, "w"), ensure_ascii=False, indent=2)
PY

cd "$DIR"
claude -p "/ticket-$ROLE $EXTRA" \
  --model "$MODEL" \
  --settings "$GEN" \
  --add-dir "$DIR" "$WORKTREES" "${REPOS[@]}" \
  -n "🤖 агент: $ROLE $(date +%d.%m\ %H:%M)" >> "$LOG" 2>&1 || echo "!!! exit $?" >> "$LOG"

# Срочное: watch.py оставляет метку p0.pending — после сбора сразу фиксер.
# Метка переживает занятую блокировку: если сбор по сигналу не стартовал, её подхватит следующий сбор.
if [ "$ROLE" = "collect" ] && [ -f "$DIR/p0.pending" ] && [[ "$EXTRA" != *--dry* ]]; then
  rm -f "$DIR/p0.pending"
  rmdir "$LOCKDIR" 2>/dev/null || true
  trap - EXIT
  exec "$0" fix --p0
fi
