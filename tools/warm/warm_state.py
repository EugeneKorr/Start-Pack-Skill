#!/usr/bin/env python3
"""Скользящий прогрев кэша (/warm): состояние, расписание и решение «пинг или пропуск».

Схема (с 19.11.2026): один повторяющийся таймер Claude Code каждые 5 минут шлёт в сессию сообщение
«Пинг прогрева кэша…». Хук UserPromptSubmit решает, нужен ли пинг: если нужен — пропускает сообщение
к модели, если нет — отклоняет его до модели (бесплатно, проверено 19.11). Любое другое сообщение в сессию
(твоё, уведомление фоновой задачи, от соседней сессии) вызывает обращение к модели, то есть само греет кэш:
оно сбрасывает счёт пингов и откладывает прогрев.

Команды:
  plan [N]  — записать состояние (N пингов после каждой паузы, по умолчанию 5, максимум 8), напечатать
              `cron <выражение>` для таймера и `cold ЧЧ:ММ` (когда остынет кэш, если уйти прямо сейчас);
  clear     — убрать состояние; печатает «WARM: был активен» или «WARM: не было»;
  hook      — для UserPromptSubmit (читает JSON со стандартного ввода).

Старое состояние (фиксированные пинги до 19.11: поля `until`, `pings`) понимается как раньше:
только строка «warm до» в шапке, пинги не блокируются.
Рубильник: удалить хук `warm_state.py hook` из ~/.claude/settings.json и команду /warm.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("WARM_STATE_DIR") or Path.home() / ".claude" / "warm")
INTERVAL_MIN = 50   # шаг пингов; кэш живёт 60 мин, запас 10 мин на сдвиг планировщика
DUE_MIN = 45        # пинг нужен, если с последнего обращения к модели прошло не меньше (тик раз в 5 мин)
CACHE_TTL_MIN = 60
DEFAULT_PINGS = 5
MAX_PINGS = 8
TICK_CRON = "*/5 * * * *"
TICK_PREFIX = "Пинг прогрева кэша"


def now() -> float:
    """Текущее время в секундах; для тестов подменяется WARM_FAKE_NOW."""
    fake = os.environ.get("WARM_FAKE_NOW")
    return float(fake) if fake else dt.datetime.now().timestamp()


def hhmm(ts: float) -> str:
    """Время ЧЧ:ММ по местным часам."""
    return dt.datetime.fromtimestamp(ts).strftime("%H:%M")


def state_file(sid: str | None = None) -> Path | None:
    """Файл состояния сессии или None, если сессия неизвестна."""
    sid = sid or os.environ.get("CLAUDE_CODE_SESSION_ID")
    return STATE_DIR / f"{sid}.json" if sid else None


def load(f: Path) -> dict[str, Any] | None:
    """Читает состояние; None, если файла нет или он битый."""
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def save(f: Path, data: dict[str, Any]) -> None:
    """Атомарная запись состояния."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(f)


def is_sliding(st: dict[str, Any]) -> bool:
    """Состояние новой (скользящей) схемы."""
    return "last_activity" in st and "n" in st


def base_time(st: dict[str, Any]) -> float:
    """Время последнего обращения к модели: сообщение или пинг."""
    return max(float(st.get("last_activity", 0)), float(st.get("last_ping", 0)))


def cold_time(st: dict[str, Any]) -> float:
    """Когда остынет кэш, если больше ничего не придёт и оставшиеся пинги дойдут."""
    left = max(0, int(st["n"]) - int(st.get("done", 0)))
    return base_time(st) + left * INTERVAL_MIN * 60 + CACHE_TTL_MIN * 60


def cmd_plan(arg: str | None) -> None:
    """Записывает состояние и печатает данные для таймера."""
    try:
        n = int(float(arg)) if arg else DEFAULT_PINGS
    except ValueError:
        n = DEFAULT_PINGS
        print("NOTE аргумент не понят — ставлю 5 пингов")
    if n > MAX_PINGS:
        print(f"NOTE больше {MAX_PINGS} пингов не ставлю: прогрев дольше ~8 ч не окупается")
    n = max(1, min(MAX_PINGS, n))
    t = now()
    st = {"n": n, "done": 0, "last_activity": t, "last_ping": 0.0, "started": t}
    f = state_file()
    if f:
        save(f, st)
    print(f"cron {TICK_CRON}")
    print(f"pings {n}")
    print(f"cold {hhmm(cold_time(st))}")


def cmd_clear() -> None:
    """Убирает состояние и говорит, был ли прогрев активен."""
    f = state_file()
    if not f or not f.exists():
        print("WARM: не было")
        return
    st = load(f) or {}
    f.unlink(missing_ok=True)
    if is_sliding(st):
        print("WARM: был активен — сними таймер")
    elif float(st.get("until", 0)) > now():
        print("WARM: был активен — сними пинги")
    else:
        print("WARM: не было (истёк)")


def emit(context: str | None = None, block: str | None = None) -> None:
    """Печатает ответ хука: блокировка или дополнительный контекст."""
    if block is not None:
        print(json.dumps({"decision": "block", "reason": block}, ensure_ascii=False))
    elif context:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": context}}, ensure_ascii=False))


def header_hint(until: float) -> str:
    """Подсказка для шапки ответа."""
    return f"Прогрев кэша идёт: допиши в конец ПЕРВОЙ строки шапки « · warm до {hhmm(until)}» (как есть, без пересказа)."


def handle_legacy(st: dict[str, Any]) -> None:
    """Старые фиксированные пинги: только строка для шапки."""
    until = float(st.get("until", 0))
    f = state_file()
    if until <= now():
        if f:
            f.unlink(missing_ok=True)
        return
    emit(context=header_hint(until))


def handle_tick(f: Path, st: dict[str, Any]) -> None:
    """Сообщение таймера: пропустить к модели (пинг) или отклонить бесплатно."""
    t = now()
    n, done = int(st["n"]), int(st.get("done", 0))
    if done >= n or t - base_time(st) < DUE_MIN * 60:
        emit(block="прогрев: пинг не нужен")
        return
    st["done"], st["last_ping"] = done + 1, t
    save(f, st)
    k = done + 1
    cold = hhmm(cold_time(st))
    text = f"Это пинг прогрева кэша {k}/{n}. Ответь ОДНОЙ строкой: шапка и слова «прогрев {k}/{n}». Ничего не запускай и не проверяй."
    if k == n:
        text += f" Это последний пинг: добавь «кэш остынет в {cold}»."
    emit(context=text + " " + header_hint(cold_time(st)))


def handle_activity(f: Path, st: dict[str, Any]) -> None:
    """Любое другое сообщение (обращение к модели): сбросить счёт пингов, показать «warm до»."""
    st["done"], st["last_activity"], st["last_ping"] = 0, now(), 0.0
    save(f, st)
    emit(context=header_hint(cold_time(st)))


def cmd_hook() -> None:
    """Хук UserPromptSubmit. Любая ошибка — молча (хук не должен мешать сообщению)."""
    try:
        try:
            inp = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            inp = {}
        prompt = str(inp.get("prompt", "")).lstrip()
        is_tick = prompt.startswith(TICK_PREFIX)
        sid = inp.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID")
        f = state_file(sid)
        st = load(f) if f and f.exists() else None
        if st is None:
            if is_tick:
                emit(block="прогрев: таймер без состояния (остался от прошлого запуска)")
            return
        if not is_sliding(st):
            handle_legacy(st)
        elif is_tick:
            handle_tick(f, st)
        else:
            handle_activity(f, st)
    except Exception:
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
