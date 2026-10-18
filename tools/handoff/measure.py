#!/usr/bin/env python3
"""Замер сессии Claude Code для /handoff-ingest.

Режимы:
    measure.py stats  [--session ID]              — токены, лимиты (текст для отчёта + JSON)
    measure.py dialog [--session ID] [--out FILE] — очищенный разговор для сортировщика/контролёра

Сессия по умолчанию — текущая (переменная CLAUDE_CODE_SESSION_ID), а не «самый свежий файл»:
в одной папке одновременно работают несколько сессий.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys
import time
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
USAGE_FILE = Path.home() / ".claude" / "usage" / "latest.json"
LIMITS_MAX_AGE_MIN = 30

# $ за 1 млн токенов: (вход, выход, чтение кэша). Запись кэша: 1.25× входа (5 мин), 2× (1 ч).
# Источник — справочник claude-api (кэш от 2026-06-24). Неизвестная модель → цены Opus 5.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-opus-5": (5.0, 25.0, 0.5),
    "claude-opus-4-8": (5.0, 25.0, 0.5),
    "claude-opus-4-7": (5.0, 25.0, 0.5),
    "claude-opus-4-6": (5.0, 25.0, 0.5),
    "claude-sonnet-5": (2.0, 10.0, 0.2),
    "claude-sonnet-4-6": (3.0, 15.0, 0.3),
    "claude-haiku-4-5": (1.0, 5.0, 0.1),
}
DEFAULT_PRICE = PRICES["claude-opus-5"]


def find_transcript(session_id: str) -> Path:
    """Находит транскрипт сессии по её ID во всех папках проектов."""
    hits = glob.glob(str(PROJECTS / "*" / f"{session_id}.jsonl"))
    if not hits:
        sys.exit(f"Транскрипт сессии {session_id} не найден в {PROJECTS}")
    return Path(hits[0])


def subagent_transcripts(main: Path) -> list[Path]:
    """Транскрипты агентов, запущенных из сессии (если Claude Code их хранит отдельно)."""
    return [Path(p) for p in glob.glob(str(main.with_suffix("") / "**" / "*.jsonl"), recursive=True)]


def read_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def price_for(model: str) -> tuple[float, float, float]:
    for key, val in PRICES.items():
        if model.startswith(key):
            return val
    return DEFAULT_PRICE


def usage_cost(model: str, u: dict) -> float:
    inp, out, read = price_for(model)
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens")
    w1 = cc.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:
        w5, w1 = u.get("cache_creation_input_tokens", 0), 0
    return (
        u.get("input_tokens", 0) * inp
        + (w5 or 0) * inp * 1.25
        + (w1 or 0) * inp * 2.0
        + u.get("cache_read_input_tokens", 0) * read
        + u.get("output_tokens", 0) * out
    ) / 1e6


def ctx_size(u: dict) -> int:
    return u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)


def collect(path: Path, main_only: bool) -> dict:
    """Считает ответы модели по уникальному message.id (одна запись ответа = несколько строк)."""
    msgs: dict[str, tuple[str, dict]] = {}
    order: list[str] = []
    for d in read_jsonl(path):
        if d.get("type") != "assistant" or (main_only and d.get("isSidechain")):
            continue
        m = d.get("message") or {}
        u, mid = m.get("usage"), m.get("id")
        if not u or not mid:
            continue
        if mid not in msgs:
            order.append(mid)
        msgs[mid] = (m.get("model", ""), u)  # последняя строка несёт итоговый usage
    ctx = [ctx_size(msgs[i][1]) for i in order]
    return {
        "calls": len(order),
        "last_ctx": ctx[-1] if ctx else 0,
        "max_ctx": max(ctx) if ctx else 0,
        "first_ctx": ctx[0] if ctx else 0,
        "sum_input": sum(ctx),
        "sum_output": sum(msgs[i][1].get("output_tokens", 0) for i in order),
        "cost": sum(usage_cost(*msgs[i]) for i in order),
        "models": sorted({msgs[i][0] for i in order if msgs[i][0]}),
    }


def new_session_estimate(main: Path) -> tuple[int, int]:
    """Медиана стартового контекста прошлых сессий этой папки (сколько весит «чистый» чат)."""
    files = sorted(main.parent.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    firsts = []
    for p in files:
        if p == main:
            continue
        for d in read_jsonl(p):
            u = (d.get("message") or {}).get("usage") if d.get("type") == "assistant" else None
            if u and not d.get("isSidechain"):
                firsts.append(ctx_size(u))
                break
        if len(firsts) >= 20:
            break
    return (int(statistics.median(firsts)) if firsts else 40_000), len(firsts)


def read_limits() -> dict | None:
    try:
        data = json.loads(USAGE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    data["age_min"] = int((time.time() - data.get("saved_at", 0)) / 60)
    return data


def fmt_usd(x: float) -> str:
    return f"${x:,.2f}" if x < 10 else f"${x:,.0f}"


def fmt_k(n: int) -> str:
    return f"{n / 1_000_000:.1f} млн" if n >= 1_000_000 else f"{round(n / 1000)} тыс."


def limits_text(lim: dict | None) -> str:
    if not lim:
        return "лимиты подписки: нет данных (строка состояния не присылала цифр) — смотри /usage"
    if lim["age_min"] > LIMITS_MAX_AGE_MIN:
        return f"лимиты подписки: данные устарели ({lim['age_min']} мин) — смотри /usage"
    r = lim.get("rate_limits") or {}
    parts = []
    fh = r.get("five_hour")
    if fh:
        s = f"5ч-окно: {int(fh.get('used_percentage', 0))}%"
        if fh.get("resets_at"):
            m = max(0, int((fh["resets_at"] - time.time()) / 60))
            s += f" (сброс через {m // 60}ч{m % 60:02d}м)"
        parts.append(s)
    if r.get("seven_day"):
        parts.append(f"неделя: {int(r['seven_day'].get('used_percentage', 0))}%")
    for k, v in r.items():
        if k not in ("five_hour", "seven_day") and isinstance(v, dict) and "used_percentage" in v:
            parts.append(f"{k.replace('seven_day_', 'неделя ')}: {int(v['used_percentage'])}%")
    t = time.strftime("%H:%M", time.localtime(lim.get("saved_at", 0)))
    return " · ".join(parts) + f" (на {t}, общий расход всех сессий)"


def cmd_stats(sid: str) -> None:
    main = find_transcript(sid)
    s = collect(main, main_only=True)
    subs = [collect(p, main_only=False) for p in subagent_transcripts(main)]
    sub_cost = sum(x["cost"] for x in subs)
    est, n = new_session_estimate(main)
    lim = read_limits()
    ratio = s["last_ctx"] / est if est else 0
    compacted = s["max_ctx"] > s["last_ctx"] * 1.5
    line = (
        f"старая сессия: ~{fmt_k(s['last_ctx'])} токенов на вопрос"
        + (f" (до сжатия было до {fmt_k(s['max_ctx'])})" if compacted else "")
        + f" → новая: ~{fmt_k(est)} (оценка по {n} прошлым стартам) · экономия ≈{ratio:.0f}× на вопрос"
        + f" · вся сессия: {s['calls']} обращений, {fmt_k(s['sum_input'])} токенов на входе"
    )
    print(line)
    print(limits_text(lim))
    print(json.dumps({"session": sid, "transcript": str(main), **s, "subagents_cost": sub_cost,
                      "subagents": len(subs), "new_estimate": est, "ratio": ratio,
                      "limits": lim}, ensure_ascii=False))


def is_noise(text: str) -> bool:
    t = text.lstrip()
    return t.startswith(("<system-reminder", "<command-", "<local-command", "Caveat:")) or not t


def cmd_dialog(sid: str, out: str | None) -> None:
    """Только реплики пользователя, текст ответов и краткий след действий (без вывода команд)."""
    main = find_transcript(sid)
    lines: list[str] = []
    seen: set[str] = set()
    for d in read_jsonl(main):
        if d.get("isSidechain") or d.get("isMeta"):
            continue
        m, typ = d.get("message") or {}, d.get("type")
        c = m.get("content")
        if typ == "user":
            texts = [c] if isinstance(c, str) else [x.get("text", "") for x in c or [] if x.get("type") == "text"]
            for t in texts:
                if not is_noise(t):
                    lines.append(f"\n### ПОЛЬЗОВАТЕЛЬ\n{t.strip()}")
        elif typ == "assistant" and isinstance(c, list):
            for x in c:
                key = f"{m.get('id')}:{json.dumps(x, ensure_ascii=False)[:200]}"
                if key in seen:
                    continue
                seen.add(key)
                if x.get("type") == "text" and x.get("text", "").strip():
                    lines.append(f"\n### CLAUDE\n{x['text'].strip()}")
                elif x.get("type") == "tool_use":
                    inp = x.get("input") or {}
                    hint = inp.get("description") or inp.get("file_path") or inp.get("command", "")
                    lines.append(f"  · [{x.get('name')}] {str(hint)[:150]}")
    text = "\n".join(lines)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"{out}: {len(text)} символов (~{len(text) // 3} токенов)")
    else:
        print(text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["stats", "dialog"])
    ap.add_argument("--session", default=os.environ.get("CLAUDE_CODE_SESSION_ID"))
    ap.add_argument("--out")
    a = ap.parse_args()
    if not a.session:
        sys.exit("Нет ID сессии: передай --session или запусти внутри Claude Code")
    cmd_stats(a.session) if a.mode == "stats" else cmd_dialog(a.session, a.out)


if __name__ == "__main__":
    main()
