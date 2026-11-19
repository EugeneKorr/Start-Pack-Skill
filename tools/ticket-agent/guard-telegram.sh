#!/usr/bin/env bash
# PreToolUse-хук: агенту можно отправлять в Telegram только в «Избранное» Владимира.
python3 -I -c '
import json, sys
d = json.load(sys.stdin)
cid = str(d.get("tool_input", {}).get("chat_id", "")).strip()
if cid in {"me", "715033350"}:
    sys.exit(0)
print("ticket-agent: отправка разрешена только в Избранное (chat_id=me)", file=sys.stderr)
sys.exit(2)
'
