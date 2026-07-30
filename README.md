# Start Pack Skill

Общий набор slash-команд и скиллов для Claude Code — чтобы работать над
проектами по одному процессу.

> Установка **не трогает** ваш `~/.claude/CLAUDE.md`: ставятся только команды.
> Личные предпочтения — язык ответа, стиль общения, привычки — остаются вашими.

## Установка

```bash
git clone https://github.com/EugeneKorr/Start-Pack-Skill.git ~/start-pack-skill
cd ~/start-pack-skill
chmod +x install.sh
./install.sh
```

После этого команды доступны **во всех** проектах, без настройки в каждом.

Обновление: `cd ~/start-pack-skill && git pull && ./install.sh`

## С чего начать

1. Прочитать [TEAM-RULES.md](TEAM-RULES.md) — общий процесс работы: когда нужен
   брейншторм, зачем self-review, как оформляются PR, что записываем в вики.
2. Поставить команды (см. выше).
3. В проекте, над которым работаете, прочитать его онбординг — например
   `docs/ONBOARDING.md` в репозитории СРМ.

## Команды

| Команда | Что делает |
|---|---|
| `/brainstorming` | Дизайн до кода: изучение контекста → уточняющие вопросы → 2–3 подхода → спек. Никакого кода до согласования |
| `/writing-plans` | Детальный план реализации: точные пути, полный код, критерий готовности каждого шага. Без заглушек и «доработать позже» |
| `/executing-plans` | Выполнение плана по шагам с проверкой после каждого и явными стоп-условиями |
| `/systematic-debugging` | Отладка через поиск первопричины. Никаких правок до понимания, что именно сломалось |
| `/tdd` | Красный → зелёный → рефакторинг: сначала падающий тест, потом минимальный код |
| `/wiki-ingest` | Сохранить знания (сессию, файл, ссылку) в вики проекта |
| `/wiki-query` | Ответить на вопрос по накопленной вики |
| `/init` | Просканировать репозиторий и обновить его `CLAUDE.md` |

## Скиллы

Скиллы подключаются на уровне проекта: скопируйте нужный в `.claude/skills/`
проекта или укажите путь в его `CLAUDE.md`.

| Скилл | Где лежит | О чём |
|---|---|---|
| database-reliability | [`database-reliability/`](database-reliability/) | Безопасные миграции PostgreSQL/Supabase: снапшот → анализ зависимостей → миграция → проверка |
| brainstorming | [`skills/brainstorming/`](skills/brainstorming/) | Дизайн до кода |
| writing-plans | [`skills/writing-plans/`](skills/writing-plans/) | Планы без плейсхолдеров |
| executing-plans | [`skills/executing-plans/`](skills/executing-plans/) | Выполнение планов со стоп-условиями |
| systematic-debugging | [`skills/systematic-debugging/`](skills/systematic-debugging/) | Поиск первопричины |
| test-driven-development | [`skills/test-driven-development/`](skills/test-driven-development/) | Красный → зелёный → рефакторинг |

## Агенты

[`agents/wiki-curator.md`](agents/wiki-curator.md) — помощник для наведения
порядка в вики проекта.

## Зачем это всё

Каждая новая сессия Claude начинается с нуля: он не помнит ни архитектуру,
ни договорённости, ни грабли, на которые вы уже наступали. Три вещи решают это:

- **`CLAUDE.md` в репозитории** — правила и контекст конкретного проекта;
- **`wiki/`** — накопленные разборы и грабли, растёт после каждой нетривиальной
  задачи;
- **общий процесс** — чтобы результат не зависел от того, кто взял задачу.

## Авторы

- Eugene Korr ([@EugeneKorr](https://github.com/EugeneKorr))
- Vladimir ([@Volight-14](https://github.com/Volight-14))

Скиллы основаны на: [obra/superpowers](https://github.com/obra/superpowers),
[deepfounder-ai/llm-wiki](https://github.com/deepfounder-ai/llm-wiki)
