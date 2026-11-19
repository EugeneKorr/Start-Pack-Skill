# Агент «тикет → фикс», ядро (этап 1) — Implementation Plan

**Цель:** общий агент для всех проектов собирает жалобы из чатов, алертов и issues в репо
задач, мелкое доводит до draft PR, утром присылает сводку по проектам. Пилот — Vega.

**Архитектура:** ядро (роли `collect` / `fix` / `digest` через `claude -p`, наблюдатель
`watch.py`, сторож отправки в Telegram) ничего не знает о проектах и читает реестр
`~/.claude/ticket-agent/projects/*.json`. Источники — модули: `telegram-chat`,
`github-issues`, `signals-table`. Этап 1 не меняет ничего в проде.

**Стек:** Claude Code CLI 2.1.185 (`-p`, `--settings`, `--add-dir`, `-n`), Telegram MCP
(`telegram`, http://127.0.0.1:8766), `gh`, launchd, bash 3.2 (macOS), python3 (stdlib).

Спек: [docs/specs/2026-10-23-ticket-agent-core.md](../specs/2026-10-23-ticket-agent-core.md).
Предыдущий план (`crm/docs/plans/2026-10-23-ticket-to-fix-agent-pilot-plan.md`): задачи 0–4
(детектор СРМ) остаются для модуля `crm-client-chat` (этап 2), задачи 7–8 заменены этим планом.

## Факты (проверено 23.10)

| Что | Значение |
|---|---|
| Пакет | `~/start-pack-skill`, ветка `feat/ticket-agent` (уже есть СРМ-версия файлов — переписываем) |
| `install.sh` | копирует `commands/*.md` → `~/.claude/commands/`, `tools/*/*` → `~/.claude/tools/` (только файлы второго уровня: подкаталоги внутри `tools/ticket-agent/` сломают `cp` при `set -e`) |
| bash | 3.2 на macOS: нет `mapfile`, нет `flock` |
| Чат VEX | `-1003335794530`; бот ошибок @nerpaservicebot `7256031940`; Владимир `715033350` |
| Репо задач Vega | `EugeneKorr/vova-workspace`, метки `vega`, `crm`, P0/P1/P2 |
| Репо Vega | crm `EugeneKorr/crmvega` (`~/crm`), калькулятор `Volight-14/vega-rates-calculator` (`~/Projects/vega-rates-calculator`), зеркало `Volight-14/vega-exchange-` (`~/Projects/vega-exchange-`) |

## Стоп-точки

**[решение]** — только по команде Владимира: PR в Start-Pack-Skill, метки в vova-workspace,
загрузка launchd, `enabled: true`, `fix_enabled: true`, любой мерж.

---

## Задача 1. Файлы ядра

Удалить СРМ-версии: `git -C ~/start-pack-skill rm --cached -q --ignore-unmatch tools/ticket-agent/watch.sh`
и `rm -f tools/ticket-agent/watch.sh` (заменён на `watch.py`). Остальные файлы перезаписать.

### 1.1. `tools/ticket-agent/config.example.json` — общие настройки

```json
{
  "enabled": false,
  "worktrees_dir": "/Users/vladimir/agent-worktrees",
  "max_tickets_per_night": 5,
  "ticket_minutes": 45,
  "digest_chat": "me"
}
```

### 1.2. `tools/ticket-agent/vega.project.example.json` — реестр пилота

```json
{
  "name": "vega",
  "title": "Vega",
  "enabled": true,
  "fix_enabled": false,
  "issues_repo": "EugeneKorr/vova-workspace",
  "issue_labels": ["vega"],
  "repos": [
    {
      "key": "crm",
      "slug": "EugeneKorr/crmvega",
      "path": "/Users/vladimir/crm",
      "label": "crm",
      "area": "СРМ операторов: заявки, чат, канбан, Люси; backend Express, frontend React, Edge-функции Supabase",
      "forbidden_paths": ["supabase/functions/bot-handler/"],
      "checks": [
        "cd backend && npm ci && npx tsc --noEmit && npm test",
        "cd frontend && npm ci && npx tsc --noEmit && npm test",
        "deno test --node-modules-dir=auto supabase/functions"
      ],
      "notes": "Edge-функции деплоятся вручную. 4 теста analyze-deal падают и на main (23.10) — не своя регрессия, не чинить попутно."
    },
    {
      "key": "calculator",
      "slug": "Volight-14/vega-rates-calculator",
      "path": "/Users/vladimir/Projects/vega-rates-calculator",
      "label": "vega",
      "area": "Расчёт курсов пар, строки таблицы Rate в Bubble, BestChange; Python FastAPI",
      "forbidden_paths": [],
      "checks": [
        "uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -e '.[dev]'",
        ".venv/bin/pytest",
        ".venv/bin/ruff check .",
        ".venv/bin/mypy app/"
      ],
      "notes": "Мерж = автодеплой. Правка старта (app/main.py, конфиг) — обязательно tests/test_startup_smoke.py и пометка в PR «перед мержем — смоук старта с прод-флагами»."
    },
    {
      "key": "mirror",
      "slug": "Volight-14/vega-exchange-",
      "path": "/Users/vladimir/Projects/vega-exchange-",
      "label": "vega",
      "area": "Зеркало: Telegram Mini App клиента для РФ (React, Supabase)",
      "forbidden_paths": [],
      "checks": ["npm ci", "CI=true npm test -- --watchAll=false", "npm run build"],
      "notes": "Push в main = автодеплой."
    }
  ],
  "fix_never": [
    "Bubble (бабл): только разбор; правки через Bubble MCP в test делает Владимир",
    "бот СРМ (supabase/functions/bot-handler): не трогаем с 21.10"
  ],
  "sources": [
    { "module": "telegram-chat", "chat_id": -1003335794530, "name": "VEX обратная связь для разработчиков", "kind": "people" },
    { "module": "telegram-chat", "chat_id": 7256031940, "name": "@nerpaservicebot", "kind": "alerts" },
    { "module": "github-issues", "repo": "EugeneKorr/vova-workspace", "labels": ["crm", "vega"], "skip_authors": ["Volight-14"] }
  ]
}
```

### 1.3. `tools/ticket-agent/run.sh`

```bash
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

# Фиксер не запускаем, если ни у одного проекта не включён fix_enabled.
if [ "$ROLE" = "fix" ]; then
  python3 -I - "$DIR" <<'PY' || exit 0
import glob, json, sys
d = sys.argv[1]
ok = any(p.get("enabled") and p.get("fix_enabled")
         for p in (json.load(open(f)) for f in glob.glob(f"{d}/projects/*.json")))
sys.exit(0 if ok else 1)
PY
fi

# Каталоги для --add-dir: каталог агента, worktree и пути репо включённых проектов.
DIRS=()
while IFS= read -r line; do DIRS+=("$line"); done < <(python3 -I - "$DIR" <<'PY'
import glob, json, sys
d = sys.argv[1]
cfg = json.load(open(f"{d}/config.json"))
print(d)
print(cfg["worktrees_dir"])
for f in sorted(glob.glob(f"{d}/projects/*.json")):
    p = json.load(open(f))
    if p.get("enabled"):
        for r in p.get("repos", []):
            print(r["path"])
PY
)

# Один прогон за раз (общая блокировка с watch.py). Старше 3 часов — прогон умер, снимаем.
LOCKDIR="$DIR/run.lock"
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  age=$(( $(date +%s) - $(stat -f %m "$LOCKDIR") ))
  if [ "$age" -gt 10800 ]; then rmdir "$LOCKDIR"; mkdir "$LOCKDIR"; else exit 0; fi
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null || true' EXIT

mkdir -p "$DIR/runs" "${DIRS[1]}"
LOG="$DIR/runs/$(date +%Y-%m-%d).log"
echo "=== $(date '+%F %T') $ROLE $EXTRA" >> "$LOG"

cd "$DIR"
claude -p "/ticket-$ROLE $EXTRA" \
  --model "$MODEL" \
  --settings "$TOOLS/settings.json" \
  --add-dir "${DIRS[@]}" \
  -n "🤖 агент: $ROLE $(date +%d.%m\ %H:%M)" >> "$LOG" 2>&1 || echo "!!! exit $?" >> "$LOG"

# Срочный сбор сразу передаёт эстафету фиксеру.
if [ "$ROLE" = "collect" ] && [[ "$EXTRA" == *--p0* ]] && [[ "$EXTRA" != *--dry* ]]; then
  rmdir "$LOCKDIR" 2>/dev/null || true
  trap - EXIT
  exec "$0" fix --p0
fi
```

### 1.4. `tools/ticket-agent/watch.py` — наблюдатель для модуля `signals-table`

```python
#!/usr/bin/env python3
"""Наблюдатель агента «тикет → фикс» (launchd, раз в 5 минут).

Для каждого включённого проекта с источником `signals-table` забирает новые строки
таблицы сигналов через REST (только чтение), кладёт их во входящие и запускает сборщик
(при P0 — срочный сбор с фиксом). Модель не вызывает; курсоры — локально в state.json.
Пока идёт прогон агента (каталог run.lock), ничего не делает: state.json пишет агент.
"""
import glob
import json
import os
import subprocess
import time
import urllib.request

DIR = os.path.expanduser("~/.claude/ticket-agent")
TOOLS = os.path.expanduser("~/.claude/tools/ticket-agent")


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def read_env(path):
    out = {}
    with open(os.path.expanduser(path)) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main():
    if not load(f"{DIR}/config.json", {}).get("enabled"):
        return
    if os.path.isdir(f"{DIR}/run.lock"):
        return
    state = load(f"{DIR}/state.json", {})
    new_rows = 0
    p0 = False
    for path in sorted(glob.glob(f"{DIR}/projects/*.json")):
        proj = load(path, {})
        if not proj.get("enabled"):
            continue
        for src in proj.get("sources", []):
            if src.get("module") != "signals-table":
                continue
            env = read_env(src["env_file"])
            url = env[src.get("url_env", "SUPABASE_URL")]
            key = env[src.get("key_env", "SUPABASE_SERVICE_ROLE_KEY")]
            cursor = f'{proj["name"]}:signals-table:{src["table"]}'
            last = int(state.get(cursor) or 0)
            req = urllib.request.Request(
                f'{url}/rest/v1/{src["table"]}?select=*&id=gt.{last}&order=id.asc&limit=200',
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                rows = json.load(resp)
            if not rows:
                continue
            os.makedirs(f"{DIR}/inbox", exist_ok=True)
            out = f'{DIR}/inbox/{proj["name"]}-{src["table"]}-{int(time.time())}.json'
            with open(out, "w") as f:
                json.dump({"project": proj["name"], "table": src["table"], "rows": rows}, f, ensure_ascii=False, indent=1)
            state[cursor] = max(r["id"] for r in rows)
            new_rows += len(rows)
            p0 = p0 or any(r.get("severity") == "P0" for r in rows)
    if not new_rows:
        return
    tmp = f"{DIR}/state.json.tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, f"{DIR}/state.json")
    subprocess.run([f"{TOOLS}/run.sh", "collect"] + (["--p0"] if p0 else []), check=False)


if __name__ == "__main__":
    main()
```

### 1.5. `tools/ticket-agent/state.sh`, `signals.sh`, `guard-telegram.sh`

Без изменений относительно СРМ-версии (`crm/docs/plans/2026-10-23-ticket-to-fix-agent-pilot-plan.md`,
разделы 7.4, 7.5, 7.6): они уже не зависят от проекта. Файлы на ветке остаются как есть.

### 1.6. `tools/ticket-agent/settings.json`

```json
{
  "permissions": {
    "allow": [
      "Read", "Edit", "Write", "Glob", "Grep", "Skill", "Task", "TodoWrite",
      "Bash(cd:*)", "Bash(ls:*)", "Bash(cat:*)", "Bash(grep:*)", "Bash(rg:*)",
      "Bash(git fetch:*)", "Bash(git worktree:*)", "Bash(git status:*)", "Bash(git diff:*)",
      "Bash(git log:*)", "Bash(git show:*)", "Bash(git add:*)", "Bash(git commit:*)",
      "Bash(git push -u origin agent/:*)",
      "Bash(npm ci:*)", "Bash(npm test:*)", "Bash(npm run test:*)", "Bash(npm run build:*)",
      "Bash(CI=true npm test:*)", "Bash(npx tsc:*)", "Bash(npx vitest:*)",
      "Bash(deno test:*)", "Bash(deno check:*)",
      "Bash(uv venv:*)", "Bash(uv pip install:*)", "Bash(.venv/bin/pytest:*)",
      "Bash(.venv/bin/ruff:*)", "Bash(.venv/bin/mypy:*)",
      "Bash(gh issue list:*)", "Bash(gh issue view:*)", "Bash(gh issue create:*)",
      "Bash(gh issue comment:*)", "Bash(gh issue edit:*)", "Bash(gh search issues:*)",
      "Bash(gh pr list:*)", "Bash(gh pr view:*)", "Bash(gh pr diff:*)", "Bash(gh pr create --draft:*)",
      "Bash(~/.claude/tools/ticket-agent/signals.sh:*)", "Bash(~/.claude/tools/ticket-agent/state.sh:*)",
      "mcp__telegram__get_history", "mcp__telegram__list_messages", "mcp__telegram__get_messages",
      "mcp__telegram__get_message_context", "mcp__telegram__search_messages", "mcp__telegram__get_chat",
      "mcp__telegram__send_message"
    ],
    "deny": [
      "Bash(gh pr merge:*)", "Bash(gh pr ready:*)", "Bash(gh pr close:*)", "Bash(gh issue close:*)",
      "Bash(gh issue delete:*)", "Bash(gh label:*)", "Bash(gh api:*)", "Bash(gh repo:*)",
      "Bash(git push origin main:*)", "Bash(git push -f:*)", "Bash(git push --force:*)",
      "Bash(git reset --hard:*)", "Bash(git checkout main:*)", "Bash(git switch main:*)",
      "Bash(git -C:*)", "Bash(rm -rf:*)", "Bash(curl:*)", "Bash(supabase:*)", "Bash(npx supabase:*)",
      "Bash(vercel:*)", "Bash(npx vercel:*)", "Bash(psql:*)",
      "mcp__telegram__reply_to_message", "mcp__telegram__forward_message", "mcp__telegram__forward_messages",
      "mcp__telegram__edit_message", "mcp__telegram__delete_message", "mcp__telegram__delete_messages_bulk",
      "mcp__telegram__send_file", "mcp__telegram__send_voice", "mcp__telegram__send_album"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "mcp__telegram__send_message",
        "hooks": [{ "type": "command", "command": "$HOME/.claude/tools/ticket-agent/guard-telegram.sh" }]
      }
    ]
  }
}
```

### 1.7. `tools/ticket-agent/install-launchd.sh`

```bash
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
    plist com.vladimir.ticket-agent.fix     "<key>StartCalendarInterval</key><array>$(at 3 0)</array>" "$TOOLS/run.sh" fix
    plist com.vladimir.ticket-agent.digest  "<key>StartCalendarInterval</key><array>$(at 7 30)</array>" "$TOOLS/run.sh" digest
    for l in $LABELS; do
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
```

### 1.8. `commands/ticket-collect.md`

```markdown
---
description: Сборщик агента «тикет → фикс» — жалобы из источников всех проектов реестра в их репо задач
---

Ты — сборщик агента «тикет → фикс». Аргументы: $ARGUMENTS (`--p0` — срочный запуск по
сигналу, `--dry` — ничего не создавать в GitHub и не двигать курсоры, только журнал).

Спек: Start-Pack-Skill `docs/specs/2026-10-23-ticket-agent-core.md`.
Настройки: `~/.claude/ticket-agent/config.json`; реестр: `~/.claude/ticket-agent/projects/*.json`
(читай все, бери только `"enabled": true`).

## Жёсткие запреты
- Людям не пишешь. Telegram — только чтение.
- В issue и журнал не переносишь реквизиты: номера карт и счетов, IBAN, кошельки, телефоны,
  суммы вместе с именем клиента. Только номер заявки/объекта, ссылка и пересказ.
- `агент:чиню` нельзя ставить, если правка затрагивает `forbidden_paths` репо или что-то
  из `fix_never` проекта, — только `агент:разбор`.

## По каждому проекту и каждому его источнику
Курсор: `~/.claude/tools/ticket-agent/state.sh get "<проект>:<модуль>:<id>"`, где id —
`chat_id` / `repo` / `table`.

Модули:
- `telegram-chat` — сообщения после курсора: `mcp__telegram__list_messages` (chat_id из
  реестра). `kind: people` — жалобы людей, учитывай ответы и контекст
  (`mcp__telegram__get_message_context`). `kind: alerts` — сообщения бота: одинаковые ошибки
  склеивай по тексту ошибки, считай повторы.
- `github-issues` — `gh issue list -R <repo> --state open --label <каждая из labels>
  --json number,title,body,author,labels,createdAt --limit 50`: номера больше курсора,
  автор не из `skip_authors`, без метки `агент`.
- `signals-table` — `~/.claude/tools/ticket-agent/signals.sh list`, файлы этого проекта;
  после обработки — `signals.sh done <файл>`.

## Для каждой находки
1. Баг или нет (вопрос, благодарность, обсуждение, плановое). Не баг — строка в журнале.
2. Дубль: `gh search issues --repo <issues_repo> --state open "<ключевые слова или номер>"`.
   Есть — `gh issue comment` «ещё случай: <источник, дата, ссылка>», дальше не идёшь.
3. Репо: сравни с `area` каждого репо проекта. Не понятно — `агент:вопрос`.
4. Метка: `агент:чиню` (один репо, одна зона, мелкое по TEAM-RULES §1, не запретное) /
   `агент:разбор` / `агент:вопрос`. Срочность: P0 — деньги, курс, недоступность, заявка не
   создаётся; P1 — мешает работе; P2 — косметика.
5. Кроме `--dry`: `gh issue create -R <issues_repo> --title "<🔴 P0|🟡 P1|🟢 P2>: <суть>"
   --label <issue_labels>,<label репо>,<P0|P1|P2>,агент,<агент:…> --body-file <файл>`.
   Тело: «Репо: <key> — <почему>», «Откуда» (источник, дата, ссылка), «Что видит человек»,
   «Шаги», «Гипотеза», для `агент:вопрос` — «Черновик вопроса автору». Последняя строка:
   «🤖 Завёл агент-сборщик».
6. Кроме `--dry`: сдвинь курсор (`state.sh set …`) на последний обработанный id/номер.

## Журнал
Раздел «сбор HH:MM» в `~/.claude/ticket-agent/runs/<ГГГГ-ММ-ДД>.md`: по проектам и
источникам — сколько прочитано, что заведено/дополнено (номера), что «не баг» и почему.
При `--p0` фиксер запустится после тебя сам (run.sh).
```

### 1.9. `commands/ticket-fix.md`

```markdown
---
description: Фиксер агента «тикет → фикс» — по issue «агент:чиню» во всех проектах фикс с тестом и draft PR
---

Ты — фиксер агента «тикет → фикс». Аргументы: $ARGUMENTS (`--p0` — только P0, `--dry` — без
push и PR). Настройки: `~/.claude/ticket-agent/config.json`, реестр
`~/.claude/ticket-agent/projects/*.json` — проекты с `enabled` и `fix_enabled`.

## Жёсткие запреты
- Никогда: мерж, push в main, деплой, запись в БД, `forbidden_paths` и `fix_never` проекта,
  сообщения людям.
- Рабочие деревья `path` репо не меняешь: только `git fetch` и `git worktree add` оттуда
  (`cd <path>`), дальше — только в своём worktree.
- Реквизиты клиентов не попадают в код, тесты, PR и комментарии.

## Отбор
По каждому проекту: `gh issue list -R <issues_repo> --label агент:чиню --state open
--json number,title,labels,body`. Общая очередь: P0 → P1 → P2, старые раньше; при `--p0` —
только P0. Всего не больше `max_tickets_per_night`. Репо — из строки «Репо: <key>» в теле.
Пропусти тикет, если твой открытый PR в этом репо (`gh pr list -R <slug> --author @me
--state open --json number,files`) меняет те же файлы, — комментарий «отложено:
пересекается с PR N».

## Для каждого тикета (до `ticket_minutes` минут)
1. `cd <path репо> && git fetch origin`, затем `git worktree add
   <worktrees_dir>/<проект>-<key>-<номер> -b agent/<номер>-<кратко> origin/main`; дальше —
   `cd` в worktree.
2. Прочитай CLAUDE.md репо и `notes` из реестра; если в репо есть `wiki/` — `/wiki-query`.
3. Сначала тест, который воспроизводит баг и падает. Не воспроизвёл — «Неудача».
4. Минимальный фикс. Потом все `checks` репо по очереди. Известные красные из `notes` не
   чинишь и не считаешь своей регрессией.
5. Интерфейс поменялся и в репо есть `docs/kb/` — блок туда. Поиск причины > 30 мин и есть
   `wiki/` — страница по `wiki/schema.md`.
6. `/code-review` по диффу; ошибки — исправь.
7. Кроме `--dry`: `git push -u origin agent/<…>`; `gh pr create --draft -R <slug>
   --title "fix(<зона>): <суть> (<issues_repo>#<номер>)" --body-file <файл>`. Тело: «Что
   сломано», «Что сделано», «Чем проверено» (команды и результат), «Агентный PR: подготовил
   агент-фиксер, мерж только после ревью Владимира» и всё обязательное из `notes` репо.
8. `gh issue comment` — ссылка на PR и «чем проверено»; `gh issue edit --remove-label
   агент:чиню --add-label агент:pr-готов`.

## Неудача
Проверка провалилась дважды подряд, не воспроизвелось, не тот репо или вышло время — без PR:
`gh issue comment` с тем, что пробовал и где застрял; `gh issue edit --remove-label агент:чиню
--add-label агент:разбор`. Worktree оставь.

## Журнал
Раздел «фикс HH:MM» в `~/.claude/ticket-agent/runs/<ГГГГ-ММ-ДД>.md`: тикеты, PR, время, неудачи.
```

### 1.10. `commands/ticket-digest.md`

```markdown
---
description: Утренняя сводка агента «тикет → фикс» по всем проектам в Избранное Telegram
---

Ты готовишь утреннюю сводку агента «тикет → фикс». Аргументы: $ARGUMENTS (`--dry` — не
отправлять, только вывести). Настройки: `~/.claude/ticket-agent/config.json`, реестр
`~/.claude/ticket-agent/projects/*.json`.

1. Журналы `~/.claude/ticket-agent/runs/` за вчера и сегодня (`*.md`, в `*.log` — строки `!!! exit`).
2. По каждому включённому проекту за 24 часа (`issues_repo`, `slug` его репо):
   🔴 P0 и их судьба; ✅ draft PR агента на ревью (номер, что сломано, чем проверено);
   🔍 `агент:разбор`; ❓ `агент:вопрос` + готовый черновик вопроса; 🗑 «не баг» из журнала.
3. ⚠️ Простои: разрыв между прогонами сборщика по расписанию больше 6 часов или `!!! exit`.
4. Без реквизитов клиентов. Нечего сообщить — «🤖 За сутки нового нет».
5. Кроме `--dry`: одно сообщение `mcp__telegram__send_message`, `chat_id: "me"`, parse_mode
   `md`, блоки по проектам с заголовком `title`. Никуда больше.
```

**Проверка задачи 1:**

```bash
cd ~/start-pack-skill
for f in run state signals guard-telegram install-launchd; do bash -n tools/ticket-agent/$f.sh || echo "FAIL $f"; done
python3 -I -m py_compile tools/ticket-agent/watch.py && echo "watch.py ok"
for j in settings config.example vega.project.example; do python3 -I -m json.tool tools/ticket-agent/$j.json > /dev/null || echo "FAIL $j"; done
echo '{"tool_input":{"chat_id":"me"}}' | bash tools/ticket-agent/guard-telegram.sh; echo "me → $?"
echo '{"tool_input":{"chat_id":-1003335794530}}' | bash tools/ticket-agent/guard-telegram.sh; echo "VEX → $?"
find tools -mindepth 3 | head -1
```

**Готово, когда:** нет `FAIL`; `me → 0`, `VEX → 2`; последняя команда пуста (в `tools/`
нет третьего уровня — `install.sh` не сломается).

---

## Задача 2. Песочница: проверка запуска без launchd и без GitHub-записи

Во временном `HOME` проверяется сама механика `run.sh` (блокировка, выход при `enabled:false`,
сбор `--add-dir`), без вызова модели: `claude` подменяется заглушкой, которая печатает аргументы.

```bash
SB=$(mktemp -d) && mkdir -p "$SB/.claude/ticket-agent/projects" "$SB/.claude/tools/ticket-agent" "$SB/bin"
cp ~/start-pack-skill/tools/ticket-agent/* "$SB/.claude/tools/ticket-agent/"
cp "$SB/.claude/tools/ticket-agent/config.example.json" "$SB/.claude/ticket-agent/config.json"
cp "$SB/.claude/tools/ticket-agent/vega.project.example.json" "$SB/.claude/ticket-agent/projects/vega.json"
printf '#!/bin/sh\necho "CLAUDE $*"\n' > "$SB/bin/claude" && chmod +x "$SB/bin/claude" "$SB"/.claude/tools/ticket-agent/*.sh
HOME="$SB" PATH="$SB/bin:$PATH" "$SB/.claude/tools/ticket-agent/run.sh" collect --dry; echo "disabled exit=$? log:"; ls "$SB/.claude/ticket-agent/runs" 2>/dev/null
python3 -I -c 'import json,sys;p=sys.argv[1];d=json.load(open(p));d["enabled"]=True;json.dump(d,open(p,"w"))' "$SB/.claude/ticket-agent/config.json"
HOME="$SB" PATH="$SB/bin:$PATH" "$SB/.claude/tools/ticket-agent/run.sh" collect --dry; cat "$SB"/.claude/ticket-agent/runs/*.log
HOME="$SB" PATH="$SB/bin:$PATH" "$SB/.claude/tools/ticket-agent/run.sh" fix; echo "fix без fix_enabled exit=$?"; grep -c "/ticket-fix" "$SB"/.claude/ticket-agent/runs/*.log
HOME="$SB" python3 -I "$SB/.claude/tools/ticket-agent/watch.py"; echo "watch exit=$?"
ls -d "$SB/.claude/ticket-agent/run.lock" 2>/dev/null || echo "lock снят"
rm -rf "$SB"
```

**Готово, когда:** при `enabled:false` логов нет; при `true` в логе строка `CLAUDE -p /ticket-collect --dry … --add-dir <агент> /Users/vladimir/agent-worktrees /Users/vladimir/crm …calculator …vega-exchange- -n 🤖 агент: collect …`;
`fix` без `fix_enabled` в лог не попал (`0`); `watch exit=0` (нет `signals-table`); блокировка снята.

---

## Задача 3. PR в Start-Pack-Skill — [решение]

`/code-review` по диффу ветки `feat/ticket-agent`, затем по команде Владимира:

```bash
cd ~/start-pack-skill
git add tools/ticket-agent commands/ticket-collect.md commands/ticket-fix.md commands/ticket-digest.md install.sh \
  docs/specs/2026-10-23-ticket-agent-core.md docs/plans/2026-10-23-ticket-agent-core-plan.md
git commit -m "feat(ticket-agent): ядро агента «тикет → фикс» для всех проектов (реестр, модули, launchd)"
git push -u origin feat/ticket-agent
gh pr create -R EugeneKorr/Start-Pack-Skill --title "Агент «тикет → фикс»: ядро для всех проектов" --body-file /tmp/ticket-agent-pr.md
```

Тело PR: что это (спек), что ставится (`install.sh` кладёт 3 команды и `tools/ticket-agent`,
ничего не включает), как включить (задача 4), что не входит (модуль СРМ — этап 2).

**Готово, когда:** PR открыт; мерж — Владимир/Женя.

---

## Задача 4. Установка и сухой прогон — [решение]

1. `cd ~/start-pack-skill && ./install.sh` (с ветки до мержа или с main после).
2. Метки в vova-workspace (команды — из прошлого плана, задача 8 п. 2: `агент`, `агент:чиню`,
   `агент:разбор`, `агент:вопрос`, `агент:pr-готов`).
3. `~/.claude/tools/ticket-agent/install-launchd.sh install` → `"enabled": true` в
   `~/.claude/ticket-agent/config.json` (`fix_enabled` в `vega.json` остаётся `false`).
   Сон Мака на зарядке Владимир отключает сам.
4. Сухие прогоны:

```bash
~/.claude/tools/ticket-agent/run.sh collect --dry
~/.claude/tools/ticket-agent/run.sh digest --dry
tail -80 ~/.claude/ticket-agent/runs/$(date +%Y-%m-%d).log
cat ~/.claude/ticket-agent/runs/$(date +%Y-%m-%d).md
launchctl list | grep ticket-agent
```

**Готово, когда:** сухой сбор прочитал VEX, бот ошибок и vova-workspace и разложил находки;
в GitHub ничего не создано, курсоры не сдвинуты; сухая сводка собрана; 4 задания в launchd.

## Задача 5. Неделя сбора, включение фиксера — [решение]

Боевой сбор по расписанию (`fix_enabled: false`) 7 дней → разбор журнала и issues с
Владимиром → `"fix_enabled": true` в `vega.json` → через 2 недели отчёт по метрикам спека.

---

## Правки по /code-review (23.10, после задач 1–2)

Код ниже в задаче 1 — исходная версия; источник правды — файлы на ветке. Изменено:

1. **Push только через `tools/ticket-agent/push-branch.sh`** (текущая ветка `agent/*` → ветка с тем же
   именем, без аргументов). `Bash(git push:*)` в deny: прежний allow `git push -u origin agent/:*`
   пропускал `agent/x:main`.
2. **`run.sh` генерирует `~/.claude/ticket-agent/settings.generated.json`**: базовые настройки +
   deny `Edit(//<path>/**)` / `Write(//<path>/**)` для каждого репо реестра. Агент правит только worktree.
3. **Секреты:** deny `Read/Edit/Write` для `**/.env` и `**/.env.*`; убраны `Bash(cat|grep|rg)`.
4. **Оболочки в deny:** `bash`, `sh`, `zsh`, `env`, `xargs`, `eval`.
5. **P0 — меткой `p0.pending`** от `watch.py`, а не аргументом. `run.sh` после любого боевого сбора
   запускает `fix --p0`, если метка есть, — срочность не теряется при занятой блокировке.
6. **`watch.py`:** ошибка одного источника пишется в stderr (launchd.log) и не останавливает остальные.
7. **`run.sh` проверяет реестр** до запуска; ошибка — строкой `!!!` в журнал прогонов. Без включённых
   проектов — выход 0 (bash 3.2 с `set -u` падает на пустом массиве).
8. **`ticket-fix.md`:** проверки — из корня worktree; пересечение — только с PR, чья ветка не `agent/*`;
   push — обёрткой.

Проверено в песочнице: deny по трём репо в сгенерированных настройках; P0-метка запускает
`fix --p0` только при `fix_enabled`; битый реестр → exit 1 + строка в журнале; битый источник
в `watch.py` → exit 0 + сообщение; обёртка отказывает с `main` и с аргументами.

## С чем может столкнуться и как разведено

| Новое | С чем | Как разведено |
|---|---|---|
| Несколько проектов в одном прогоне | лимит фиксов | общий `max_tickets_per_night` на все проекты, общая очередь по срочности |
| Репо разных проектов | рабочие деревья Владимира | только `fetch` + `worktree add`; worktree в `<worktrees_dir>/<проект>-<репо>-<issue>`; `git -C`, `checkout/switch main`, `reset --hard` запрещены |
| `watch.py` и прогон агента | одновременная запись `state.json` | наблюдатель молчит, пока есть `run.lock`; `run.sh` держит его весь прогон |
| launchd-задания между собой | наложение сбора, фикса, сводки | одна блокировка `run.lock` на все роли, старше 3 ч снимается |
| `install.sh` Start-Pack-Skill | подкаталоги в `tools/ticket-agent/` | реестр-пример лежит плоско (`vega.project.example.json`) |
| Хук `pr-review-gate` | `gh pr create` фиксера | фиксер всегда делает `/code-review` до PR |
| Известные красные тесты | «починка» попутно | в `notes` репо, фиксер их не трогает |
| Issues Владимира в vova-workspace | дубли его задач | `skip_authors: ["Volight-14"]` |
| Сессии агента | ручной учёт часов | название «🤖 агент: …» |
| Модуль СРМ (этап 2) | ядро | подключается строкой `signals-table` в `vega.json`, ядро не меняется |

## Self-review плана

- [x] **Покрытие спека.** Реестр, модули `telegram-chat` / `github-issues` / `signals-table`, три роли, сторож, безопасность, порядок включения, откат (`enabled: false`, `uninstall`). Модуль СРМ вынесен в этап 2.
- [x] **Без плейсхолдеров.** Все id, пути и команды взяты из фактов на 23.10.
- [x] **Согласованность.** Ключ курсора `<проект>:<модуль>:<id>` одинаков в `watch.py` и `ticket-collect.md`. Поля реестра (`repos[].key/slug/path/label/area/forbidden_paths/checks/notes`, `fix_never`, `sources[]`) одинаковы в примере, `run.sh` и командах.
- [x] **Зависимости.** Файлы → песочница → PR → установка → неделя сбора → фиксер.
- [x] **macOS bash 3.2.** Нет `mapfile` и `flock`: массив `DIRS` читается в цикле `while read`, блокировка — через `mkdir`.
- [x] **Особенность `${DIRS[1]}`.** Это `worktrees_dir`: Python печатает его вторым, сразу после каталога агента.
