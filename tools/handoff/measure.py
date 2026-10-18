#!/usr/bin/env python3
"""Замеры сессии Claude Code для /handoff-ingest, /handoff-query, /economy и счётчика в шапке.

Режимы:
    measure.py stats  [--session ID]            токены, лимиты (текст + JSON)
    measure.py dialog [--session ID] [--out F]  очищенный разговор (без вывода команд)
    measure.py prep   [--session ID]            всё для хендоффа одним вызовом → ~/.claude/handoff/<ID>/
    measure.py query-prep                       что принимать новой сессии: записки, неразложенные слепки
    measure.py gauge                            строка для шапки (хук UserPromptSubmit); молчит ниже порога
    measure.py limits                           лимиты подписки одной строкой

Сессия по умолчанию — текущая (CLAUDE_CODE_SESSION_ID), а не «самый свежий файл»:
в одной папке одновременно работают несколько сессий.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
PROJECTS = HOME / ".claude" / "projects"
HANDOFF_DIR = HOME / ".claude" / "handoff"
LIMITS_SH = HOME / ".claude" / "tools" / "usage" / "limits.sh"
STATUSLINE_FILE = HOME / ".claude" / "usage" / "latest.json"

GAUGE_MIN_CTX = 150_000       # ниже — счётчик молчит
GAUGE_WINDOW_WARN = 0.80      # доля окна модели, после которой предупреждаем об автосжатии
HANDOFF_CALLS = 5             # обращений с полным контекстом у хендоффа-«слепка»
DEFAULT_CALLS_PER_Q = 7       # пока в сессии меньше 3 вопросов
TAIL_BYTES = 2_000_000        # хвост транскрипта для gauge
RECENT_QUESTIONS = 5          # окно для «обращений на вопрос» и роста
C0_TTL = 86_400               # кэш стартового контекста папки — сутки

NOISE_PREFIXES = ("<system-reminder", "<command-", "<local-command", "Caveat:", "<cross-session-message",
                  "<ide_opened_file", "[Request interrupted")


# ---------- транскрипт ----------

def session_id(explicit: str | None) -> str:
    sid = explicit or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        sys.exit("Нет ID сессии: передай --session или запусти внутри Claude Code")
    return sid


def find_transcript(sid: str) -> Path:
    hits = glob.glob(str(PROJECTS / "*" / f"{sid}.jsonl"))
    if not hits:
        sys.exit(f"Транскрипт сессии {sid} не найден в {PROJECTS}")
    return Path(hits[0])


def read_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def ctx_size(u: dict) -> int:
    return u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)


def user_text(d: dict) -> str:
    """Текст сообщения пользователя или '' (вывод команд и служебные вставки — не считаются)."""
    if d.get("type") != "user" or d.get("isSidechain") or d.get("isMeta"):
        return ""
    c = (d.get("message") or {}).get("content")
    if isinstance(c, str):
        t = c
    elif isinstance(c, list):
        t = "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    else:
        return ""
    t = t.strip()
    return "" if not t or t.startswith(NOISE_PREFIXES) else t


def model_window(model: str) -> int:
    return 200_000 if "haiku" in model else 1_000_000


# ---------- замер сессии ----------

def collect(path: Path, main_only: bool = True) -> dict:
    """Один ответ модели пишется несколькими строками — считаем по уникальному message.id."""
    msgs: dict[str, tuple[str, dict]] = {}
    order: list[str] = []
    prompts = 0
    started = None
    for d in read_jsonl(path):
        if started is None and d.get("timestamp"):
            started = d["timestamp"]
        if user_text(d):
            prompts += 1
        if d.get("type") != "assistant" or (main_only and d.get("isSidechain")):
            continue
        m = d.get("message") or {}
        u, mid = m.get("usage"), m.get("id")
        if not u or not mid:
            continue
        if mid not in msgs:
            order.append(mid)
        msgs[mid] = (m.get("model", ""), u)
    ctx = [ctx_size(msgs[i][1]) for i in order]
    models = sorted({msgs[i][0] for i in order if msgs[i][0]})
    return {
        "calls": len(order), "prompts": prompts, "started": started,
        "last_ctx": ctx[-1] if ctx else 0, "max_ctx": max(ctx) if ctx else 0,
        "first_ctx": ctx[0] if ctx else 0, "sum_input": sum(ctx),
        "sum_output": sum(msgs[i][1].get("output_tokens", 0) for i in order),
        "models": models, "model": msgs[order[-1]][0] if order else "",
    }


def new_session_estimate(main: Path) -> tuple[int, int]:
    """Медиана стартового контекста прошлых сессий папки (кэш на сутки — для хука)."""
    cache = HANDOFF_DIR / f"c0-{main.parent.name}.json"
    try:
        c = json.loads(cache.read_text())
        if time.time() - c["at"] < C0_TTL:
            return c["c0"], c["n"]
    except (OSError, KeyError, json.JSONDecodeError):
        pass
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
    c0, n = (int(statistics.median(firsts)) if firsts else 50_000), len(firsts)
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"c0": c0, "n": n, "at": time.time()}))
    return c0, n


def fmt_k(n: int) -> str:
    return f"{n / 1_000_000:.1f} млн" if n >= 1_000_000 else f"{round(n / 1000)} тыс."


# ---------- лимиты подписки ----------

def fetch_limits() -> dict | None:
    """limits.sh (ключ входа из связки) → список как на экране /usage; запасной путь — файл строки состояния."""
    if LIMITS_SH.exists():
        try:
            out = subprocess.run([str(LIMITS_SH)], capture_output=True, text=True, timeout=15).stdout
            data = json.loads(out)
            if "limits" in data:
                return {"source": "server", "at": time.time(), "limits": data["limits"]}
        except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
            pass
    try:
        s = json.loads(STATUSLINE_FILE.read_text())
        r = s.get("rate_limits") or {}
        lim = []
        if r.get("five_hour"):
            lim.append({"kind": "session", "percent": r["five_hour"].get("used_percentage"),
                        "resets_at": r["five_hour"].get("resets_at")})
        if r.get("seven_day"):
            lim.append({"kind": "weekly_all", "percent": r["seven_day"].get("used_percentage")})
        return {"source": "statusline", "at": s.get("saved_at", 0), "limits": lim}
    except (OSError, json.JSONDecodeError):
        return None


def _reset_text(v) -> str:
    try:
        ts = datetime.fromisoformat(str(v)).timestamp() if not isinstance(v, (int, float)) else float(v)
    except ValueError:
        return ""
    m = max(0, int((ts - time.time()) / 60))
    if m < 24 * 60:
        return f"сброс через {m // 60}ч{m % 60:02d}м"
    return "сброс " + datetime.fromtimestamp(ts).strftime("%a %d.%m %H:%M")


def limits_text(lim: dict | None) -> str:
    if not lim or not lim.get("limits"):
        return "лимиты подписки: нет данных — смотри /usage"
    age = int((time.time() - lim["at"]) / 60)
    if age > 30:
        return f"лимиты подписки: данные устарели ({age} мин) — смотри /usage"
    parts = []
    for l in lim["limits"]:
        kind, pct = l.get("kind"), l.get("percent")
        if pct is None:
            continue
        if kind == "session":
            parts.append(f"5ч-окно: {int(pct)}% ({_reset_text(l.get('resets_at'))})")
        elif kind == "weekly_all":
            parts.append(f"неделя: {int(pct)}%")
        elif kind == "weekly_scoped":
            name = ((l.get("scope") or {}).get("model") or {}).get("display_name") or "модель"
            parts.append(f"неделя {name}: {int(pct)}%")
    return " · ".join(parts) + " (общий расход всех сессий)"


# ---------- stats / dialog ----------

def stats_lines(sid: str, with_limits: bool = True) -> tuple[str, str, dict]:
    main = find_transcript(sid)
    s = collect(main)
    est, n = new_session_estimate(main)
    ratio = s["last_ctx"] / est if est else 0
    compacted = s["max_ctx"] > s["last_ctx"] * 1.5
    line = (
        f"старая сессия: ~{fmt_k(s['last_ctx'])} токенов на вопрос"
        + (f" (до сжатия было до {fmt_k(s['max_ctx'])})" if compacted else "")
        + f" → новая: ~{fmt_k(est)} (по {n} прошлым стартам) · экономия ≈{ratio:.0f}× на вопрос"
        + f" · вся сессия: {s['prompts']} вопросов, {s['calls']} обращений, {fmt_k(s['sum_input'])} токенов на входе"
    )
    lim = fetch_limits() if with_limits else None
    info = {"session": sid, "transcript": str(main), "project_dir": main.parent.name, **s,
            "new_estimate": est, "ratio": ratio, "window": model_window(s["model"]), "limits": lim}
    return line, limits_text(lim), info


def cmd_stats(sid: str) -> None:
    line, lim, info = stats_lines(sid)
    print(line)
    print(lim)
    print(json.dumps(info, ensure_ascii=False))


def dialog_text(main: Path) -> str:
    """Только реплики пользователя, текст ответов и одна строка на каждое действие."""
    lines: list[str] = []
    seen: set[str] = set()
    for d in read_jsonl(main):
        t = user_text(d)
        if t:
            lines.append(f"\n### ПОЛЬЗОВАТЕЛЬ\n{t}")
            continue
        if d.get("type") != "assistant" or d.get("isSidechain"):
            continue
        m = d.get("message") or {}
        for x in m.get("content") or []:
            if not isinstance(x, dict):
                continue
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
    return "\n".join(lines)


def cmd_dialog(sid: str, out: str | None) -> None:
    text = dialog_text(find_transcript(sid))
    if out:
        Path(out).write_text(text, encoding="utf-8")
        print(f"{out}: {len(text)} символов (~{len(text) // 3} токенов)")
    else:
        print(text)


# ---------- prep: всё для хендоффа одним вызовом ----------

def sh(cmd: list[str], cwd: str | None = None) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20, cwd=cwd).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def wiki_titles(d: Path) -> str:
    idx = d / "index.cache.json"
    if not idx.exists():
        return "(вики нет)"
    try:
        data = json.loads(idx.read_text())
    except json.JSONDecodeError:
        return "(index.cache.json не читается)"
    pages = data.get("pages") or data if isinstance(data, (list, dict)) else []
    items = pages.values() if isinstance(pages, dict) else pages
    out = []
    for p in items:
        if isinstance(p, dict):
            out.append(f"- {p.get('slug') or p.get('file') or '?'}: {p.get('title', '')} [{', '.join(p.get('tags') or [])}]")
    return "\n".join(out) or "(страниц нет)"


def chat_title(main: Path) -> str:
    t = ""
    for d in read_jsonl(main):
        if d.get("type") == "custom-title":
            t = d.get("customTitle", "")
    return t


TRANSLIT = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z", "и": "i",
            "й": "j", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t",
            "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
            "э": "e", "ю": "yu", "я": "ya"}


def strip_emoji_prefix(name: str) -> str:
    """Снимает с начала эмодзи, включая цифровые 1️⃣2️⃣3️⃣ (цифра + keycap), и ведущие @."""
    return re.sub(r"^(?:[0-9]️?⃣|[^\w@])+", "", name.strip()).lstrip("@ ").strip()


def slugify(name: str) -> str:
    s = "".join(TRANSLIT.get(ch, ch) for ch in strip_emoji_prefix(name).lower())
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "main"


def note_header(project: Path, slug: str) -> str:
    """Шапка записки нити (или старого единого файла) — чтобы не читать её отдельным обращением."""
    threads = project / "docs" / "handoff"
    f = threads / f"{slug}.md" if threads.is_dir() else project / "docs" / "HANDOFF.md"
    if not f.exists():
        return f"записка: {f.relative_to(project)} — нет (новая)"
    head = "".join(f.read_text(encoding="utf-8").splitlines(keepends=True)[:6])
    return f"записка: {f.relative_to(project)}\n{head}"


def cmd_prep(sid: str) -> None:
    line, lim, info = stats_lines(sid)
    main = Path(info["transcript"])
    project = Path.cwd()
    out = HANDOFF_DIR / sid
    out.mkdir(parents=True, exist_ok=True)
    dialog = dialog_text(main)
    (out / "dialog.md").write_text(dialog, encoding="utf-8")
    since = (info["started"] or "")[:10]
    git = sh(["git", "log", "--oneline", f"--since={since}"], str(project)) if since else ""
    prs = sh(["gh", "pr", "list", "--state", "merged", "--limit", "30",
              "--json", "number,title,mergedAt", "--jq", ".[] | \"#\\(.number) \\(.mergedAt[:10]) \\(.title)\""], str(project))
    ctx_md = (f"# Контекст сессии {sid}\n\nНачало: {info['started']}\nПапка: {project}\n\n"
              f"## Коммиты с начала сессии\n{git or '(нет)'}\n\n## Смёрженные PR (последние 30)\n{prs or '(gh недоступен или PR нет)'}\n\n"
              f"## Страницы вики проекта\n{wiki_titles(project / 'wiki')}\n\n## Страницы общей вики (~/.claude/wiki)\n{wiki_titles(HOME / '.claude' / 'wiki')}\n")
    (out / "context.md").write_text(ctx_md, encoding="utf-8")
    title = chat_title(main)
    base = strip_emoji_prefix(title)
    slug = slugify(base) if base else "main"
    mode = "Б (вики пишет агент — контекст выше 90% окна)" if info["last_ctx"] > 0.9 * info["window"] else "А (слепок пишешь ты)"
    info.update({"dir": str(out), "title": title, "base": base, "slug": slug,
                 "threads": (project / "docs" / "handoff").is_dir(), "dialog_tokens": len(dialog) // 3})
    (out / "stats.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    print(f"ЗАМЕР: {line}")
    print(f"ЛИМИТЫ: {lim}")
    print(f"РЕЖИМ: {mode}")
    print(f"ПАПКА: {out}  (dialog.md ~{fmt_k(len(dialog) // 3)} токенов, context.md, stats.json)")
    print(f"ЧАТ: «{title or '(без названия)'}» · база «{base or '?'}» · нить/slug: {slug} · "
          f"формат: {'по нитям (docs/handoff/)' if info['threads'] else 'один файл docs/HANDOFF.md'}")
    print(f"НАЧАЛО СЕССИИ: {info['started']}")
    print(note_header(project, slug))
    print(f"ТРАНСКРИПТ: {main}")


# ---------- query-prep: что принимать новой сессии ----------

def cmd_query_prep(sid: str) -> None:
    project = Path.cwd()
    main = find_transcript(sid)
    s = collect(main)
    threads = project / "docs" / "handoff"
    print(f"ЭТА СЕССИЯ: {sid} · стартовый контекст {fmt_k(s['first_ctx'])} · транскрипт {main}")
    notes = sorted(threads.glob("*.md")) if threads.is_dir() else [project / "docs" / "HANDOFF.md"]
    print(f"ФОРМАТ: {'по нитям' if threads.is_dir() else 'один файл'}")
    for n in notes:
        if not n.exists() or n.name in ("INDEX.md", "README.md"):
            continue
        head = n.read_text(encoding="utf-8").splitlines()[:4]
        status = next((h for h in head if h.startswith("Статус:")), "Статус: ?")
        print(f"ЗАПИСКА: {n.relative_to(project)} · {status} · {head[0][:90] if head else ''}")
    # неразложенные слепки этого проекта (агент упал или сессию закрыли раньше)
    proj_key = main.parent.name
    for d in sorted(HANDOFF_DIR.glob("*/dump.md")):
        st = d.parent / "stats.json"
        try:
            meta = json.loads(st.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("project_dir") == proj_key and not (d.parent / "done").exists():
            print(f"СЛЕПОК НЕ РАЗЛОЖЕН: {d} (сессия {meta.get('session')}, нить {meta.get('slug')}) — доразложи агентом")


# ---------- gauge: строка для шапки ----------

def tail_entries(path: Path) -> list[dict]:
    size = path.stat().st_size
    with open(path, "rb") as f:
        if size > TAIL_BYTES:
            f.seek(size - TAIL_BYTES)
            f.readline()  # обрезанная строка
        raw = f.read().decode("utf-8", errors="ignore")
    out = []
    for line in raw.splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def cmd_gauge() -> None:
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        return
    hits = glob.glob(str(PROJECTS / "*" / f"{sid}.jsonl"))
    if not hits:
        return
    main = Path(hits[0])
    entries = tail_entries(main)
    # обращения и вопросы в хвосте: группируем обращения по вопросам
    per_q: list[int] = []
    ctx_at_q: list[int] = []
    seen: set[str] = set()
    last_ctx, model = 0, ""
    for d in entries:
        if user_text(d):
            per_q.append(0)
            ctx_at_q.append(last_ctx)
            continue
        if d.get("type") == "assistant" and not d.get("isSidechain"):
            m = d.get("message") or {}
            u, mid = m.get("usage"), m.get("id")
            if u and mid and mid not in seen:
                seen.add(mid)
                last_ctx, model = ctx_size(u), m.get("model", model)
                if per_q:
                    per_q[-1] += 1
    if last_ctx < GAUGE_MIN_CTX:
        return
    recent = [n for n in per_q[-RECENT_QUESTIONS - 1:-1] if n > 0] if len(per_q) > 1 else []
    k = round(statistics.mean(recent)) if len(recent) >= 3 else DEFAULT_CALLS_PER_Q
    k_note = "" if len(recent) >= 3 else " (оценка)"
    c0, _ = new_session_estimate(main)
    saving = k * (last_ctx - c0)
    payback = HANDOFF_CALLS * last_ctx / saving if saving > 0 else 0
    parts = [f"📏 контекст {fmt_k(last_ctx)}"]
    if payback > 0:
        parts.append(f"хендофф окупится через {max(1, round(payback))} вопр.")
    if k >= 5:
        parts.append(f"или /effort medium — ≈{max(3, round(k * 0.55))} обращений на вопрос вместо {k}{k_note}")
    window = model_window(model)
    if last_ctx >= GAUGE_WINDOW_WARN * window:
        parts.append(f"⚠️ {int(100 * last_ctx / window)}% окна — скоро автосжатие, хендофф сейчас")
    text = " · ".join(parts)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                      "additionalContext": f"Счётчик контекста (вторая строка шапки, как есть): {text}"}},
                     ensure_ascii=False))


# ---------- main ----------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["stats", "dialog", "prep", "query-prep", "gauge", "limits"])
    ap.add_argument("--session")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.mode == "gauge":
        cmd_gauge()
    elif a.mode == "limits":
        print(limits_text(fetch_limits()))
    else:
        sid = session_id(a.session)
        {"stats": lambda: cmd_stats(sid), "dialog": lambda: cmd_dialog(sid, a.out),
         "prep": lambda: cmd_prep(sid), "query-prep": lambda: cmd_query_prep(sid)}[a.mode]()


if __name__ == "__main__":
    main()
