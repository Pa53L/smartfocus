# SmartFocus

**Проактивный агент фокус-сессий** — расширение Ouroboros для управления концентрацией, приоритизацией задач и адаптивными рекомендациями.

SmartFocus работает как интегрированное расширение внутри цикла Ouroboros: companion-процесс мониторит сессии в фоновом режиме, виджет показывает live-дашборд, а инструменты доступны агенту для автоматизации всего пайплайна работы.

---

## Возможности

### Управление задачами

- **Единый список задач** — задачи из всех источников (ручной ввод, Thunderbird email, демо-данные) попадают в общий список и оцениваются по матрице Эйзенхауэра
- **Поле `source`** — каждая задача помечена источником: `manual`, `email`, `message`, `calendar`, `synthetic`
- **Матрица Эйзенхауэра** — детерминированный scoring: важность × срочность + 8 факторов (дедлайн, явный приоритет, связь с дневной целью, сложность, доступное время, влияние, цена неисполнения, повторные напоминания)
- **ТОП-3 на сегодня** — три задачи с максимальным priority_score
- **Выпадающий список задач** — при старте сессии задачи выбираются из dropdown, отсортированного по оценке Эйзенхауэра

### Фокус-сессии

- **Старт/стоп через виджет** — одна кнопка, надпись меняется: «Start Session» когда сессии нет, «Stop Session» когда идёт (`visible_when` conditional rendering)
- **Work Tools** — настраиваемый список рабочих приложений. Время в этих приложениях считается как сфокусированное. OpenIDE включён по умолчанию. Добавление/удаление через виджет
- **Авто-трекинг активного приложения** — companion каждые 30 сек определяет frontmost app на macOS (через `osascript`) и записывает activity: `is_related=True` для рабочих инструментов, `False` для остальных
- **DND (Do Not Disturb)** — автоматическое включение Focus Mode на macOS при старте сессии, выключение при стопе (через AppleScript Control Center)
- **Адаптивная длительность** — recommends_duration учитывает readiness, complexity, time_to_meeting; после сессии next_session_duration_min корректируется на основе FocusScore

### FocusScore

Прозрачная метрика 0–1, взвешенная сумма 4 компонент:

| Компонента | Вес | Формула |
|---|---|---|
| Focused Time Ratio (FTR) | 0.55 | `focused_time / total_duration` |
| Switch Stability | 0.20 | `1.0 - (unplanned_switches / total_switches)` |
| Recovery Rate | 0.15 | `1.0 - avg_recovery_seconds / 300` |
| Goal Progress | 0.10 | `1.0 if goal_achieved else 0.3` |

**Процесс важнее результата**: FTR = 55% — больше половины. Можно не завершить задачу, но если реально работал — Score будет высоким. Goal Progress — всего 10%.

### Мониторинг и авто-стоп

- **Промежуточный FocusScore** — каждые 5 минут companion считает Score на активной сессии и записывает в `focus_checks[]`
- **Порог 0.6** — при падении ниже порога:
  - **Первый раз** — nudge в чат: «⚠️ Focus score dropped below threshold»
  - **Второй раз** — `auto_stop_session()` — сессия останавливается автоматически, DND выключается, отправляется nudge
- **Пропуск при отсутствии данных** — если нет activity/switches, focus_check пропускается (предотвращает ложные авто-стопы)

### Уведомления и email

- **Thunderbird polling** — companion сканирует INBOX каждые 3 минуты, ищет `[task-XXX]` в темах писем, импортирует как задачи с `source=email`
- **Приоритет-фильтр** — во время активной сессии: если входящее email-событие выше приоритетом текущей задачи → nudge показывается. Остальные — молча откладываются для отчёта. Без сессии — nudge о всех task emails
- **Сводка уведомлений** — после stop_session: total_emails, task_emails, non_task_emails, focus_check_scores, deferred_count
- **Cyrillic support** — RFC 2047 декодирование заголовков (поверх `decode_header` + `make_header`)

### Дневная сводка

- **Авто-триггер** — companion проверяет каждый цикл: если `hour >= day_summary_hour` (по умолчанию 18:00) и есть ≥1 завершённая сессия сегодня и сводка ещё не отправлена → генерирует и отправляет сводку в чат
- **Содержание** — sessions_count, total_focused_minutes, avg_focus_score, completed/incomplete/carried_over tasks, best_focus_hour, distraction_sources, recommendation на завтра
- **Ручной вызов** — `get_day_summary` tool или `/day-summary` route

### Preflight-проверки

При старте companion проверяет:
- **Host Service** — `/identity` endpoint на loopback
- **Thunderbird** — `find_thunderbird_profile()`, если None → email scanning отключается с warning
- **osascript** — `shutil.which("osascript")`, если не найден → activity tracking отключается с warning

Это предотвращает stderr-noise каждые 30 сек / 3 мин когда зависимости недоступны.

### Виджет (Dashboard)

Декларативный виджет на вкладке Widgets:
- **Active Session** — статус, задача, цель, elapsed/planned minutes, FocusScore
- **TOP-3 Tasks** — таблица с Source, Quadrant, Score, Explanation
- **Eisenhower Matrix** — markdown-визуализация квадрантов
- **Start/Stop Session** — переключаемая кнопка с `visible_when`
- **Task dropdown** — выпадающий список задач (`type: select`, `options_target`, `options_path`) отсортированный по Эйзенхауэру
- **Work Tools** — текущий список, формы добавления/удаления
- **Email Report** — письма за время сессии

### Прочее

- **Адаптивные рекомендации** — observation → rationale → proposed_change → accept/reject/observe
- **Knowledge base** — AI Q&A сохраняются как Markdown в vault
- **Calendar-aware slots** — propose_focus_slots учитывает историю FocusScore по часам и конфликты с calendar_events
- **Session continuation** — continue_task наследует goal, work_tools, recommended_duration из прошлой сессии

---

## Архитектура

```
plugin.py          — PluginAPI: 22 инструмента, 19 маршрутов, виджет, настройки, companion
companion.py       — фоновый монитор: activity tracking, email scan, focus check, day summary
state.py           — SQLite (WAL mode, 7 таблиц, busy_timeout=10s) + JSON→SQLite миграция
models.py          — dataclass модели (Task, FocusSession, AppSwitch, Notification, ...)
config.py          — константы, веса, дефолты
prioritize.py      — матрица Эйзенхауэра + scoring + TOP-3
focus_score.py     — формула FocusScore (FTR + SS + RR + GP)
session.py         — lifecycle сессий: start/stop/auto_stop/continue/propose_slots
notifications.py   — очередь и фильтрация уведомлений (show_now vs defer)
normalize.py       — дедупликация, линковка, нормализация
adapt.py           — движок адаптации с proposals
knowledge.py       — Q&A + Markdown vault
synthetic.py       — синтетические датасеты для демо (5 задач в 3 сценариях)
email_scanner.py   — incremental Thunderbird mbox scanner + create_tasks_from_emails
dnd.py             — macOS Do Not Disturb / Focus mode toggle
report.py          — дневные отчёты
```

### SQLite-хранилище

Все данные в `smartfocus.db` (SQLite, WAL mode) под skill state directory:

| Таблица | Содержимое |
|---|---|
| `tasks` | Задачи (id, title, source, source_ref, deadline, importance, urgency, complexity, quadrant, status, priority_score, ...) |
| `sessions` | Сессии (id, task_id, goal, start/end_time, planned/actual_duration, focused_time, status, focus_score, work_tools, focus_checks, ...) |
| `proposals` | Адаптивные предложения |
| `settings` | Настройки (key-value) |
| `knowledge` | База знаний |
| `journal` | Журнал действий (timestamp, action, details, actor) |
| `email_state` | Состояние email-сканера (seen_ids, offset) |
| `session_emails` | Письма, полученные во время сессий |

При первом запуске существующие JSON-файлы автоматически мигрируются в SQLite, оригиналы переименовываются в `.migrated`.

---

## Инструменты (22)

| Инструмент | Описание |
|---|---|
| `start_session` | Начать фокус-сессию (task_id, goal, expected_result, readiness, work_tools) |
| `stop_session` | Остановить сессию (goal_achieved, task_status: completed/break/deferred, feedback) |
| `get_status` | Текущий статус: активная сессия, задачи, недавние сессии |
| `add_task` | Добавить задачу (source=manual) |
| `prioritize_tasks` | Запустить приоритизацию по Эйзенхауэру |
| `get_top3` | ТОП-3 задачи на сегодня |
| `scan_sources` | Загрузить демо-датасет |
| `get_focus_score` | Breakdown FocusScore активной/последней сессии |
| `get_report` | Дневной отчёт |
| `ask_ai` | Вопрос во время сессии → Markdown в vault |
| `get_proposals` | Адаптивные предложения |
| `accept_proposal` | Принять proposal |
| `configure_sources` | Настройки источников и сессий |
| `propose_focus_slots` | Предложить слоты фокус-работы (с учётом календаря) |
| `get_day_summary` | Сводка дня |
| `get_session_summary` | Сводка последней сессии |
| `continue_task` | Продолжить задачу из прошлой сессии |
| `reset_demo` | Сброс состояния |
| `record_activity` | Записать activity (app, duration) |
| `record_switch` | Записать переключение приложения |
| `process_notifications` | Пропустить уведомления через фильтр |
| `scan_email` | Ручной скан Thunderbird INBOX |
| `get_email_report` | Письма за время сессии |

## Маршруты (19)

`status`, `matrix`, `start`, `stop`, `scan`, `config/save`, `config`, `top3`, `proposals`, `report`, `email/scan`, `email/report`, `slots`, `day-summary`, `session-summary`, `reset`, `tasks/select`, `work_tools`, `work_tools/add`, `work_tools/remove`

---

## Установка

### Требования

- Ouroboros v6.61.12+
- macOS (для DND и activity tracking через osascript)
- Thunderbird (опционально — для email scanning)
- Accessibility permissions (для osascript — трекинг активного приложения)

### Установка

1. Скопируйте файлы скилла в `~/Ouroboros/data/skills/external/smartfocus/`:
   ```bash
   git clone https://github.com/Pa53L/smartfocus.git
   cp -r smartfocus/* ~/Ouroboros/data/skills/external/smartfocus/
   ```

2. Перезапустите Ouroboros

3. Скилл появится в Settings → Skills. Review запустится автоматически (tri-model). При `warnings` — скилл executable.

4. Откройте вкладку Widgets → SmartFocus для доступа к дашборду

### Настройка

- **Work Tools** — добавьте названия приложений, в которых работаете (виджет → формы Add/Remove Work Tool). Сопоставление case-insensitive по подстроке.
- **Thunderbird Profile Path** — оставьте пустым для авто-детекта, или укажите путь вручную (Settings → SmartFocus)
- **Day Summary Hour** — час автоматической дневной сводки (по умолчанию 18:00)
- **Enable DND on Session Start** — включать ли Focus Mode автоматически (по умолчанию true)
- **Focus Score Threshold** — порог авто-стопа (по умолчанию 0.6)

---

## Демо-режим

1. Нажмите **Scan Sources** в виджете (или вызовите `scan_sources`) — загрузятся синтетические задачи
2. Нажмите **Scan Email** — импорт задач из Thunderbird
3. Нажмите **Prioritize** — оценка по Эйзенхауэру
4. Выберите задачу из dropdown → заполните Goal → **Start Session**
5. Поработайте в OpenIDE/IDE — companion будет трекать focused time
6. Нажмите **Stop Session** → выберите статус (completed/break/deferred)
7. В 18:00 (или при вызове `get_day_summary`) — сводка дня

---

## Технологии

- **Python 3** (stdlib only — sqlite3, json, mailbox, email, urllib, subprocess)
- **SQLite** (WAL mode, busy_timeout=10s) — без внешних зависимостей
- **Ouroboros PluginAPI** — declarative widgets, companion process, Host Service chat injection
- **macOS osascript** — DND toggle + frontmost app detection

## Лицензия

MIT
