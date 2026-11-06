#!/usr/bin/env bash
# Курсоры сборщика: state.sh get <key> | set <key> <value>
set -euo pipefail
F="$HOME/.claude/ticket-agent/state.json"
python3 -I - "$F" "$@" <<'PY'
import json, os, sys
f, cmd, key = sys.argv[1], sys.argv[2], sys.argv[3]
d = json.load(open(f)) if os.path.exists(f) else {}
if cmd == "get":
    print(d.get(key, ""))
elif cmd == "set":
    d[key] = sys.argv[4]
    tmp = f + ".tmp"
    json.dump(d, open(tmp, "w"), ensure_ascii=False, indent=2)
    os.replace(tmp, f)
else:
    sys.exit(2)
PY
