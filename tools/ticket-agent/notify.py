#!/usr/bin/env python3
"""Отправка сводки агента «тикет → фикс» в «Избранное» Telegram Владимира.

Текст — со stdin. Адрес зашит (chat_id «me»), другого получателя скрипт не принимает.
Идёт в локальный Telegram MCP (http://127.0.0.1:8766/mcp). Агенту инструмент
mcp__telegram__send_message запрещён; запуск этого скрипта Владимир разрешил явно
правилом в своих ~/.claude/settings.json (решение 26.10.2026).
--dry — только показать, что ушло бы.
"""
import json
import sys
import urllib.request

URL = "http://127.0.0.1:8766/mcp"
CHAT = "me"
LIMIT = 3900  # запас до лимита Telegram в 4096 символов


def rpc(body, sid=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        headers["Mcp-Session-Id"] = sid
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode()
        sid = resp.headers.get("Mcp-Session-Id") or sid
    lines = [l[5:].strip() for l in raw.splitlines() if l.startswith("data:")] or [raw]
    return sid, (json.loads(lines[-1]) if lines[-1].strip() else None)


def chunks(text):
    out, cur = [], ""
    for para in text.split("\n"):
        if len(cur) + len(para) + 1 > LIMIT and cur:
            out.append(cur)
            cur = ""
        cur += para + "\n"
    if cur.strip():
        out.append(cur)
    return out


def send(sid, text, parse_mode):
    args = {"chat_id": CHAT, "message": text}
    if parse_mode:
        args["parse_mode"] = parse_mode
    _, res = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "send_message", "arguments": args}}, sid)
    res = res or {}
    return "error" not in res and not res.get("result", {}).get("isError")


def main():
    dry = sys.argv[1:] == ["--dry"]
    if sys.argv[1:] and not dry:
        sys.exit("notify.py: аргументы не принимаются, кроме --dry")
    text = sys.stdin.read().strip()
    if not text:
        sys.exit("notify.py: пустой текст")
    parts = chunks(text)
    if dry:
        print(f"[dry] ушло бы в Избранное: {len(parts)} сообщ.")
        return
    sid, _ = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                             "clientInfo": {"name": "ticket-agent-notify", "version": "1"}}})
    rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    for i, part in enumerate(parts, 1):
        # Markdown может не пройти разбор — тогда тот же текст без разметки.
        if not (send(sid, part, "md") or send(sid, part, None)):
            sys.exit(f"notify.py: часть {i}/{len(parts)} не отправлена")
    print(f"отправлено в Избранное: {len(parts)} сообщ.")


if __name__ == "__main__":
    main()
