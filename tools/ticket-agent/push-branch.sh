#!/usr/bin/env bash
# Единственный способ агента запушить: только текущая ветка agent/…, в ветку с тем же именем.
# Прямой `git push` агенту запрещён (settings.json): refspec вида agent/x:main иначе ушёл бы в main.
set -euo pipefail
branch=$(git rev-parse --abbrev-ref HEAD)
case "$branch" in
  agent/*) ;;
  *) echo "push-branch: можно пушить только ветки agent/… (сейчас: $branch)" >&2; exit 2 ;;
esac
if [ "$#" -ne 0 ]; then echo "push-branch: аргументы не принимаются" >&2; exit 2; fi
git push -u origin "refs/heads/$branch:refs/heads/$branch"
