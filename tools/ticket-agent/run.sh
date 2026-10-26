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
# Сухой прогон (--dry): дополнительно запрещены все записи наружу — GitHub, push, курсоры, Telegram.
GEN="$DIR/settings.generated.json"
DRY=0; [[ "$EXTRA" == *--dry* ]] && DRY=1
python3 -I - "$TOOLS/settings.json" "$GEN" "$DRY" "${REPOS[@]}" <<'PY'
import json, sys
base, out, dry, repos = sys.argv[1], sys.argv[2], sys.argv[3] == "1", sys.argv[4:]
s = json.load(open(base))
deny = s["permissions"]["deny"]
for r in repos:
    deny += [f"Edit(/{r}/**)", f"Write(/{r}/**)"]
if dry:
    deny += [
        "Bash(gh issue create:*)", "Bash(gh issue comment:*)", "Bash(gh issue edit:*)",
        "Bash(gh pr create:*)", "Bash(~/.claude/tools/ticket-agent/push-branch.sh)",
        "Bash(~/.claude/tools/ticket-agent/state.sh set:*)", "Bash(~/.claude/tools/ticket-agent/signals.sh done:*)",
        "Bash(git commit:*)", "Bash(git worktree:*)", "Bash(~/.claude/tools/ticket-agent/notify.py:*)",
    ]
json.dump(s, open(out, "w"), ensure_ascii=False, indent=2)
PY

# Долгоживущий токен для безлюдного режима (`claude setup-token`): строка
# CLAUDE_CODE_OAUTH_TOKEN=… в auth.env (chmod 600). Без него — обычный вход CLI, который протухает.
# Файл не исполняется: берём значение после «CLAUDE_CODE_OAUTH_TOKEN=» и склеиваем строки-продолжения
# (setup-token переносит длинный токен, и при копировании он может лечь в несколько строк).
if [ -f "$DIR/auth.env" ]; then
  if ! TOKEN=$(python3 -I - "$DIR/auth.env" <<'PY'
import sys
lines = [l.strip() for l in open(sys.argv[1]) if l.strip() and not l.lstrip().startswith("#")]
key = "CLAUDE_CODE_OAUTH_TOKEN="
for i, l in enumerate(lines):
    if l.startswith(key):
        parts = [l[len(key):].strip().strip("'\"")]
        for cont in lines[i + 1:]:
            if "=" in cont:
                break
            parts.append(cont.strip("'\""))
        print("".join(parts))
        sys.exit(0)
sys.exit("в auth.env нет строки CLAUDE_CODE_OAUTH_TOKEN=")
PY
  ); then
    echo "!!! $(date '+%F %T') $ROLE: $TOKEN" >> "$LOG"
    exit 1
  fi
  export CLAUDE_CODE_OAUTH_TOKEN="$TOKEN"
fi

cd "$DIR"
claude -p "/ticket-$ROLE $EXTRA" \
  --model "$MODEL" \
  --settings "$GEN" \
  --add-dir "$DIR" "$WORKTREES" "${REPOS[@]}" \
  -n "🤖 агент: $ROLE $(date +%d.%m\ %H:%M)" < /dev/null >> "$LOG" 2>&1 || echo "!!! exit $?" >> "$LOG"

# После каждого боевого сбора — фиксер (решение 26.10: не ночью, а 3 раза в день небольшими порциями).
# Метка p0.pending от watch.py больше ничего не меняет в запуске (P0 и так первые в очереди),
# снимаем её, чтобы не копилась. Без fix_enabled фиксер выходит сразу, не вызывая модель.
if [ "$ROLE" = "collect" ] && [[ "$EXTRA" != *--dry* ]]; then
  rm -f "$DIR/p0.pending"
  rmdir "$LOCKDIR" 2>/dev/null || true
  trap - EXIT
  exec "$0" fix
fi
