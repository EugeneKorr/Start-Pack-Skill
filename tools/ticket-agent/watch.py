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
import sys
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
            cursor = f'{proj.get("name")}:signals-table:{src.get("table")}'
            try:
                env = read_env(src["env_file"])
                url = env[src.get("url_env", "SUPABASE_URL")]
                key = env[src.get("key_env", "SUPABASE_SERVICE_ROLE_KEY")]
                last = int(state.get(cursor) or 0)
                req = urllib.request.Request(
                    f'{url}/rest/v1/{src["table"]}?select=*&id=gt.{last}&order=id.asc&limit=200',
                    headers={"apikey": key, "Authorization": f"Bearer {key}"},
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    rows = json.load(resp)
            except Exception as e:  # один сломанный источник не останавливает остальные
                print(f"{time.strftime('%F %T')} watch {cursor}: {type(e).__name__}: {e}", file=sys.stderr)
                continue
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
    if p0:
        # Метка, а не аргумент: если сбор сейчас не стартует (занята блокировка),
        # фиксер запустится после ближайшего сбора.
        open(f"{DIR}/p0.pending", "w").close()
    subprocess.run([f"{TOOLS}/run.sh", "collect"], check=False)


if __name__ == "__main__":
    main()
