#!/bin/bash
# Лимиты подписки Claude (5ч-окно, неделя, Fable) — как на экране /usage.
# Ключ входа берётся из связки ключей macOS и НИКУДА не сохраняется и не печатается.
# Адрес сервера недокументирован — может перестать работать; тогда скрипт печатает ошибку, не падает.
# Вывод: JSON ответа сервера (stdout). Рубильник: удалить этот файл.

set -o pipefail
svc="Claude Code-credentials"

creds=$(security find-generic-password -s "$svc" -w 2>/dev/null) || {
  echo '{"error":"нет записи в связке ключей: '"$svc"'"}'; exit 1; }

token=$(printf '%s' "$creds" | jq -r '.claudeAiOauth.accessToken // empty')
exp=$(printf '%s' "$creds" | jq -r '.claudeAiOauth.expiresAt // 0')
unset creds
[ -z "$token" ] && { echo '{"error":"в записи нет accessToken"}'; exit 1; }
now_ms=$(( $(date +%s) * 1000 ))
[ "$exp" -gt 0 ] && [ "$exp" -lt "$now_ms" ] && { echo '{"error":"ключ входа истёк — открой любой чат Claude Code, он обновится"}'; exit 1; }

resp=$(curl -sS --max-time 10 -w '\n%{http_code}' \
  -H "Authorization: Bearer $token" \
  -H "anthropic-beta: oauth-2025-04-20" \
  -H "Accept: application/json" \
  "https://api.anthropic.com/api/oauth/usage")
unset token
code=$(printf '%s' "$resp" | tail -n1)
body=$(printf '%s' "$resp" | sed '$d')
[ "$code" = "200" ] || { echo "{\"error\":\"сервер ответил $code\",\"body\":$(printf '%s' "$body" | jq -R . )}"; exit 1; }
printf '%s\n' "$body"
