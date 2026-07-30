#!/usr/bin/env bash
# Start-Pack-Skill / install.sh — устанавливает slash-команды в ~/.claude/commands/
#
# Личный ~/.claude/CLAUDE.md НЕ трогаем — у каждого он свой.
# Общие правила совместной работы лежат в TEAM-RULES.md рядом с этим скриптом.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
COMMANDS_DIR="$CLAUDE_DIR/commands"

echo "=== Start Pack Skill: установка ==="
echo "Источник: $SCRIPT_DIR"
echo "Цель:     $COMMANDS_DIR"
echo ""

mkdir -p "$COMMANDS_DIR"

for cmd in "$SCRIPT_DIR/commands/"*.md; do
    name=$(basename "$cmd")
    # Бэкап, если команда с таким именем уже стоит и отличается
    if [ -f "$COMMANDS_DIR/$name" ] && ! cmp -s "$cmd" "$COMMANDS_DIR/$name"; then
        cp "$COMMANDS_DIR/$name" "$COMMANDS_DIR/$name.bak.$(date +%Y%m%d_%H%M%S)"
        echo "• Сохранил прежнюю версию: $name.bak.*"
    fi
    cp "$cmd" "$COMMANDS_DIR/$name"
    echo "✓ Команда: ~/.claude/commands/$name"
done

echo ""
echo "=== Готово! ==="
echo ""
echo "Доступные команды во всех проектах:"
echo "  /brainstorming         — дизайн до кода: вопросы → подходы → спек"
echo "  /writing-plans         — детальный план реализации без заглушек"
echo "  /executing-plans       — выполнение плана по шагам, со стоп-условиями"
echo "  /systematic-debugging  — отладка через поиск первопричины"
echo "  /tdd                   — цикл «красный → зелёный → рефакторинг»"
echo "  /wiki-ingest           — сохранить знания сессии в вики проекта"
echo "  /wiki-query            — ответить на вопрос по накопленной вики"
echo "  /init                  — скан репозитория и обновление CLAUDE.md проекта"
echo ""
echo "Твой личный ~/.claude/CLAUDE.md не изменён."
echo "Общие правила работы над проектами: $SCRIPT_DIR/TEAM-RULES.md"
echo ""
echo "Скилл для проектов с Supabase (подключается вручную):"
echo "  database-reliability/SKILL.md"
echo ""
echo "Обновление: git pull && ./install.sh"
