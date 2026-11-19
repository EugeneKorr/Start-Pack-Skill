#!/usr/bin/env python3
"""Состояние прогрева кэша (/warm) для шапки ответа.

Команды:
  plan [N]  — посчитать N пингов через 55 мин (по умолчанию 5, 1..8), записать
              «тёплый до» в ~/.claude/warm/<session>.json и напечатать расписание;
  clear     — убрать состояние; печатает «WARM: был активен» или «WARM: не было»;
  hook      — для UserPromptSubmit: если прогрев идёт, отдать строку для шапки.

Рубильник: удалить хук `warm_state.py hook` из ~/.claude/settings.json и команду /warm.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".claude" / "warm"
INTERVAL_MIN = 50  # кэш живёт 60 мин; запас 10 мин на сдвиг планировщика (17.11: при 55 два пинга опоздали и сами оплатили перезапись)
CACHE_TTL_MIN = 60
DEFAULT_PINGS = 5
MAX_PINGS = 8


def state_file() -> Path | None:
    """Файл состояния текущей сессии или None, если сессия неизвестна."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    return STATE_DIR / f"{sid}.json" if sid else None


def cmd_plan(arg: str | None) -> None:
    """Печатает расписание пингов и записывает время остывания кэша."""
    try:
        n = int(float(arg)) if arg else DEFAULT_PINGS
    except ValueError:
        n = DEFAULT_PINGS
        print("NOTE аргумент не понят — ставлю 5 пингов")
    if n > MAX_PINGS:
        print(f"NOTE больше {MAX_PINGS} пингов не ставлю: прогрев дольше ~8 ч не окупается")
    n = max(1, min(MAX_PINGS, n))
    now = dt.datetime.now()
    for i in range(1, n + 1):
        t = now + dt.timedelta(minutes=INTERVAL_MIN * i)
        print(f"{i}/{n} {t.strftime('%-M %-H %-d %-m *')} {t.strftime('%H:%M')}")
    cold = now + dt.timedelta(minutes=INTERVAL_MIN * n + CACHE_TTL_MIN)
    print(f"cold {cold.strftime('%H:%M')}")
    f = state_file()
    if f:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"until": cold.timestamp(), "pings": n}), encoding="utf-8")


def read_until(f: Path) -> float | None:
    """Время остывания из файла состояния или None."""
    try:
        return float(json.loads(f.read_text(encoding="utf-8"))["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cmd_clear() -> None:
    """Убирает состояние и говорит, был ли прогрев активен."""
    f = state_file()
    if not f or not f.exists():
        print("WARM: не было")
        return
    until = read_until(f)
    f.unlink(missing_ok=True)
    active = until is not None and until > dt.datetime.now().timestamp()
    print("WARM: был активен — сними пинги" if active else "WARM: не было (истёк)")


def cmd_hook() -> None:
    """Строка для шапки, пока прогрев идёт; истёкшее состояние удаляет. Ошибки молча."""
    try:
        f = state_file()
        if not f or not f.exists():
            return
        until = read_until(f)
        if until is None or until <= dt.datetime.now().timestamp():
            f.unlink(missing_ok=True)
            return
        hhmm = dt.datetime.fromtimestamp(until).strftime("%H:%M")
        text = (f"Прогрев кэша идёт: допиши в конец ПЕРВОЙ строки шапки « · warm до {hhmm}» "
                f"(как есть, без пересказа).")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": text}}, ensure_ascii=False))
    except Exception:  # хук не должен мешать сообщению
        return


def main() -> None:
    """Точка входа."""
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "plan":
        cmd_plan(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "clear":
        cmd_clear()
    elif cmd == "hook":
        cmd_hook()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
