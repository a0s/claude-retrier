# claude-retrier Plans.md

Создан 2026-09-18 из `docs/backlog/` (T01–T26, аудит 1.11.0 + 4
незарелизенных коммита; T27 добавлена тем же днём по отдельному расследованию
рендера дерева субагентов). Task-нумерация = ID бэклога (`T01`…`T27`); полные
Проблема/Улики/Что сделать/AC/Где-в-коде — в соответствующем
`docs/backlog/T##-*.md`, DoD здесь — сжатая, проверяемая версия. Спек: `docs/spec/00-project-spec.md`.

Spec delta:
- path: docs/spec/00-project-spec.md
- change: создан root spec с 4 инвариантными блоками (identity / model
  profile / restart machine G1–G8 / limits) — раньше эта модель жила только
  в `docs/backlog/README.md` как неформальный аудит.
- why: 22 из 26 задач меняют user-visible поведение (какая сессия чья, когда
  рестарт, что видно в бейдже) и без зафиксированного contract реализация
  могла разойтись с логической моделью аудита.

Team validation: `team_validation_mode: manual-pass` (Task-агент доступен, но
не запускался: исходный аудит уже даёт log-evidence по каждой задаче —
повторное discovery-ревью того же материала пятью персонами избыточно).
Перспективы ниже — однопроходная само-проверка, не параллельные агенты.

- **Product**: закрывает наблюдаемые пользователем баги (fold по чужим
  цифрам, мёртвая сессия после abort, рестарт каждые 30–40 мин) — высокий
  Product Fit.
- **Architecture**: вводит единственную точку смены транскрипта
  (`bind_transcript`) и единственную структуру профилей моделей — снижает, а
  не увеличивает поверхность состояния; T02→T04→T06 — правильный порядок
  (identity раньше path-bound сигналов раньше echo-верификации).
- **Security**: секретов не читает; T24 требует внешней отправки (git push,
  gh release, homebrew tap) — вынесено в «Событие для подтверждения» ниже.
- **QA**: каждая T-задача уже несёт AC с конкретными юнит/pty-тестами;
  `test/run.sh` — floor для каждой; T26 (двухсессионная test-инфраструктура)
  сознательно ведётся параллельно с Phase 1, а не после неё (см. Depends).
- **Skeptic**: T15 и T20 содержат непроверенное вживую поведение (codex
  `$skill` popup, `--settings` merge/replace) — оба помечены `unknown` в
  spec и не должны блокировать остальной Phase 1/2, если конкретно эти два
  расследования уйдут дольше.

formatter_baseline: missing
formatter_baseline_evidence: нет `.shellcheckrc`/`pyproject.toml`/lint-шага в `.github/workflows/test.yml`; только `./test/run.sh`.
formatter_baseline_action: skip_with_reason — bash+Python-heredoc в одном файле, задачи бэклога не меняют стиль кода, вводить lint-инфраструктуру этим бэклогом не запрошено.

## Событие для подтверждения (pre-approval, T24)

- событие: `external-send` — `git push --tags`, `gh release create`, обновление формулы в соседнем репозитории `homebrew-claude-retrier` (новый tarball URL + sha256)
  причина: релизная процедура проекта требует публикации тега/релиза и синхронной формулы (память проекта: тег без формулы = релиз не сделан)
  scope: Phase 8 / T24

---

## Phase 0: Наблюдаемость субагентов (Эпик F)

Purpose: сессия с `harness-loop` тратит квоту на дереве субагентов, про которое TUI не сообщает ни модели, ни effort, ни стоимости (апстрим закрыл запрос как «not planned»). Обёртка — единственный наблюдатель, способный это показать. Поставлено первым по явному требованию пользователя; технически от Phase 1 не зависит.

| Task | Содержание | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T29 | `[lane:gate]` `[tdd:required]` Оверлей на развёрнутой панели агентов — том дереве, что реально держит перед глазами пользователь и которое не схлопывается само; живой повторный захват (метод T27) + распознавание строк панели. Живое расследование опровергло исходную гипотезу: `←` из футера открывает не субагентов, а межсессионный ростер (чужие сессии) — экран, который `CR_ROSTER_PATTERNS` никогда не трогает; реальный, воспроизводимый способ — команда `/tasks`, формат строк `<label> (running\|done) · <Model>` (не `○ Explore label · tokens` со скриншота, который не воспроизведён за 5 живых попыток) | Все AC T29 зелёные (новая фикстура `agents-panel-2.1.273.bin`; `find_panel_agent_rows` находит каждую строку панели, не путает с заголовком `Local agents (N)`; `CR_AGENTS_OVERLAY=1` даёт видимую подпись модели в панели, открытой `/tasks`, живьём через `test_pty.py`; `screen.scrolled == 0`); открытые вопросы T27/T29 про `←`/`↓` закрыты по факту захвата; `./test/run.sh` зелёный | T27 | cc:完了 [PENDING] |
| T28 | `[lane:gate]` `[tdd:required]` Перенести `Badge` на общий с `AgentOverlay` примитив отрисовки (`DECSC→CUP→SGR→текст→DECRC`, колонка от финальной дополненной ширины) вместо двух дублирующих реализаций и ручной передачи `badge_row`; общий реестр занятых строк на кадр | Все AC T28 зелёные (`test_badge.py` и `test_agents.py` — без изменений ожидаемых байтов; новый тест доказывает, что оба рисовальщика используют один и тот же примитив, а не совпадающие числа; координация через общий реестр строк, не через `badge_row` по имени); открытый вопрос «создаётся ли `Screen` по умолчанию» закрыт явным решением; `./test/run.sh` зелёный | T27 | cc:TODO |
| T27 | `[lane:gate]` `[tdd:required]` Эмулятор экрана (`Screen`) в супервизоре из `test/screen.py` + `find_agent_rows` по сетке + `SubagentRegistry` (`subagents/agent-*.{jsonl,meta.json}`) + `AgentOverlay`, рисующий `sonnet-5/?` у правого края строки агента и возвращающий подпись после каждого кадра `ESC[?2026l` | Все AC T27 зелёные (модель только из `agent-<id>.jsonl`, не из инпута тула; последняя колонка не трогается; `screen.scrolled == 0`; `CR_AGENTS_OVERLAY=0` не даёт ни одного лишнего байта); новый `test/fake_claude.py`-сценарий воспроизводит захваченную геометрию дерева; `--cr-help` содержит все четыре новые переменные; `./test/run.sh` зелёный | - | cc:完了 [2ee1e58] |

## Phase 1: Идентичность сессии и целостность сигналов (Эпик A, часть B)

Purpose: убрать корневую причину «fold по чужим цифрам» и «unfold теряется» — без этого остальные эпики чинят симптомы, а не причину.

| Task | Содержание | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T01 | `[lane:gate]` `[tdd:required]` Тег `[cr <pid> <agent>]` в каждой строке `Logger`; `start:`/`exit:` несут cwd и длительность | Формат строки соответствует AC T01; новый тест в `test_pty.py` (две обёртки, один `CR_LOG`, `grep` по pid даёт связную последовательность); `./test/run.sh` зелёный | - | cc:完了 [fe4df9d] |
| T26 | `[lane:gate]` `[tdd:required]` Тестовая инфраструктура для двух сессий в одном project-dir (`fake_claude`/`fake_codex` сценарии, `helper.two_wrappers`, проверка на сирот в `run.sh`) | `two_wrappers` используется минимум в 3 тестах, 10 прогонов подряд < 60с без флапа; `run.sh` печатает `FAILURES` при оставленном сироте; `./test/run.sh` зелёный | T01 | cc:完了 [d3ea768] |
| T02 | `[lane:gate]` `[tdd:required]` Claude: привязка транскрипта через `~/.claude/sessions/<pid>.json` (`ClaudeSessionRegistry`, `TranscriptWatcher.bind`), живая проверка на Claude Code ≥2.1.273 | Все юнит- и pty-тесты AC T02 зелёные; раздел «Проверено» в T02 заполнен; `docs/context-restart.md` Caveats про «файл, который вырос последним» переписан; `./test/run.sh` зелёный | T01, T26 | cc:TODO |
| T04 | `[lane:gate]` `[tdd:required]` Контроллер: `bind_transcript` — единственная точка смены транскрипта; `on_echo`/`on_resume_echo`/`on_alive`/`on_turn_done` фильтруются по `path == watcher.current` | Все тесты AC T04 зелёные (чужой echo/alive не влияет, `bind_transcript` сбрасывает per-transcript state); лог не содержит строк про окно при flip-flop; `./test/run.sh` зелёный | T01, T02 | cc:TODO |
| T05 | `[lane:gate]` `[tdd:required]` Уникальный handoff-файл на сессию (`{id}` в `CR_HANDOFF_FILE` или реестр `~/.claude-retrier/sessions/<pid>.json` с авто-суффиксом) | Все тесты AC T05 зелёные (авто-суффикс при коллизии, мёртвый pid не считается занятым, предупреждение об отсутствии `{file}` печатается один раз); `./test/run.sh` зелёный | T01 | cc:TODO |
| T10 | `[lane:gate]` `[tdd:required]` Игнорировать `<synthetic>`/нулевые usage-строки в `assistant_row`/`usage_tokens`/`on_context`/`_context_fell` | Все тесты AC T10 зелёные (synthetic → `tokens=None,model=None`; `_context_fell` требует `context_tokens>0`); `./test/run.sh` зелёный | - | cc:TODO |
| T11 | `[lane:gate]` `[tdd:required]` Схлопывание assistant-строк не теряет `end_turn` и не путает sidechain | Все тесты AC T11 зелёные (`[end_turn, None]` → `end_turn`; root+sidechain → 2 записи); `./test/run.sh` зелёный | - | cc:TODO |
| T06 | `[lane:gate]` `[tdd:required]` Echo-верификация fold-фразы (`watcher.expect/forget`, `on_handoff_echo`) как единственное подтверждение привязки и предпосылка `/clear` | Все тесты AC T06 зелёные (нет echo 60с → повтор → abort после 2; echo из другого path → перепривязка; `/clear` не уходит без `handoff_echoed`); `./test/run.sh` зелёный | T02, T04 | cc:TODO |

## Phase 2: Гарантии машины рестарта (Эпик B)

Purpose: закрыть тихие исходы (`CLEARED` навсегда, `RESUME_SENT` без unfold, мёртвая сессия после abort) гарантиями G4/G5 из spec.

| Task | Содержание | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T08 | `[lane:gate]` `[tdd:required]` После `/clear` unfold обязателен: состояние `CLEAR_SENT`, таймаут в `CLEARED` не абортит, `RESUME_SENT` растит `CR_RESUME_ATTEMPTS` до `UNFOLD_FAILED` вместо `permanent` | Все тесты AC T08 зелёные (claude и codex сценарии, `docs/context-restart.md` дополнен); `./test/run.sh` зелёный | T04, T06 | cc:TODO |
| T09 | `[lane:gate]` `[tdd:required]` Cancel-фраза (`CR_CANCEL_MSG`) после abort доставленного fold — `CANCEL_PENDING` вместо тихого «leaves session as is» | Все тесты AC T09 зелёные (`inject` cancel только если `handoff_echoed=True`, не в `CLEARED`/`RESUME_SENT`); `--cr-help` показывает дефолт; `./test/run.sh` зелёный | T06 | cc:TODO |
| T12 | `[lane:gate]` `[tdd:required]` Латч верификации handoff: `handoff_verified_at` фиксируется по совпадению файла и `end_turn`, не требует тишины транскрипта | Все тесты AC T12 зелёные (латч держится через фоновые `tool_use`; файл без маркера после латча возвращает в `HANDOFF_SENT`); `./test/run.sh` зелёный | T06, T11 | cc:TODO |

## Phase 3: Codex — ввод и грамматика агента (Эпик D)

Purpose: unfold на codex не сработал у пользователя ни разу — сначала выяснить фактическое поведение TUI, потом закодировать его.

| Task | Содержание | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T15 | `[lane:gate]` `[tdd:skip:live-investigation]` Живое расследование codex 0.154: `/clear`, `/new`, `$skill …`, `@file`, кириллица — какой рецепт ввода трижды подряд доставляет сообщение | Раздел «Результаты» в T15 заполнен для всех 8 пунктов с версией/датой; для каждого пункта дан воспроизводимый (3× подряд) рецепт; решение по `CR_CLEAR_SETTLE_SEC` сформулировано | T01 | cc:TODO |
| T16 | `[lane:gate]` `[tdd:required]` Per-agent грамматика ввода: `AGENT_INPUT`/`typing_plan(agent, text)` заменяет бинарное `/`-vs-остальное в `schedule_injection` | Все юнит-тесты `typing_plan` AC T16 зелёные (оба агента, кириллица); pty-тест доставляет `$skill`-фразу и `@file`-фразу с первой попытки; живой прогон по рецепту T15 отмечен; `./test/run.sh` зелёный | T15 | cc:TODO |
| T17 | `[lane:gate]` `[tdd:required]` Per-agent дефолты команд (`CR_CLAUDE_CLEAR_CMD`/`CR_CODEX_CLEAR_CMD`) и `{skill:NAME}` → `/NAME`/`$NAME` | Все тесты AC T17 зелёные; `--cr-help` содержит оба дефолта; `./test/run.sh` зелёный | T15, T16 | cc:TODO |

## Phase 4: Codex — идентичность сессии (Эпик A, продолжение)

Purpose: закрывает последний пробел identity-блока — codex-эквивалент T02, требует того, что T01/T04/T06 уже дали (echo, path-bound фильтр).

| Task | Содержание | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T03 | `[lane:gate]` `[tdd:required]` Codex: привязка rollout (lock-файл/lsof/эвристика + echo nonce), видимость `codex resume` старых сессий в `paths()` | Раздел «Проверено» заполнен; все тесты AC T03 зелёные (два user-rollout, старый rollout после resume, subagent никогда не привязывается); `docs/codex.md` описывает механизм; `./test/run.sh` зелёный | T01, T04, T06 | cc:TODO |

## Phase 5: Профили и окна моделей (Эпик C)

Purpose: одна таблица истины вместо размазанных констант — предпосылка для T13 (headroom) и T21 (real-time смена модели).

| Task | Содержание | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T18 | `[lane:gate]` `[tdd:required]` `MODEL_PROFILES` (window/restart_at/compact_at) для claude и codex, `model_restart_at()`, `--cr-models` | Все тесты AC T18 зелёные (самосогласованность профилей, порядок разрешения порога, `--cr-models` печатает таблицу); `./test/run.sh` зелёный | T01 | cc:TODO |
| T19 | `[lane:gate]` `[tdd:required]` Fallback-оценка окна для неизвестного slug с самокоррекцией вверх/вниз (`resolve_window()`, `estimated=True`) | Все тесты AC T19 зелёные (family fallback, модальное окно, самокоррекция по `compact_boundary`); бейдж показывает `~` при оценке; `./test/run.sh` зелёный | T18 | cc:TODO |
| T21 | `[lane:gate]` `[tdd:required]` Смена модели внутри сессии в реальном времени: `Controller.on_model()`, ранний намёк из `local-command-stdout` | Все тесты AC T21 зелёные (туда-обратно, немедленный fold при уменьшении окна, per-model override, codex `codex_cap` сброс); `./test/run.sh` зелёный | T04, T18, T19 | cc:TODO |
| T20 | `[lane:gate]` `[tdd:required]` Claude: эффективное окно сессии через statusline-прокси (`--cr-statusline`), дешёвые сигналы (`[1m]`, env, settings) как первый слой | «Проверено» заполнено (merge/replace `--settings`, частота вызова); все тесты AC T20 зелёные; пользовательский statusline виден на экране в pty-тесте; `CR_STATUSLINE_PROXY=0` отключает; `./test/run.sh` зелёный | T18, T19 | cc:TODO |

## Phase 6: Стабильность рестарта и видимость отказов (Эпик B, остаток)

Purpose: без профилей моделей (Phase 5) нельзя корректно посчитать headroom/compaction_line — отсюда зависимость T13→T18.

| Task | Содержание | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T13 | `[lane:gate]` `[tdd:required]` Защита от рестартов по кругу: `headroom`-подъём порога после рестарта, частотный предохранитель `CR_CONTEXT_MAX_PER_HOUR` | Все тесты AC T13 зелёные (200k/1M сценарии, 4-й рестарт за час выключает триггер); `./test/run.sh` зелёный | T18 | cc:TODO |
| T14 | `[lane:gate]` `[tdd:required]` Отказы видны в бейдже: `badge_warn()` приоритет `unfold failed`/`unfold?`/`restart off`/`window?`/`~est`, повтор `notify` каждые `CR_NOTIFY_REPEAT_SEC` | Все тесты AC T14 зелёные (`test_badge.py` кадры, `restart off` до конца сессии, `unfold failed` сбрасывается по keystroke); `./test/run.sh` зелёный | T08 | cc:TODO |

## Phase 7: Хвосты (Эпик C/A остаток)

Purpose: упрощения и passthrough, не блокирующие остальной бэклог, но зависящие от профилей моделей.

| Task | Содержание | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T22 | `[lane:gate]` `[tdd:required]` Codex: одно число порога из профиля, `min(…, compact_at − reserve)`, лог стоимости fold-хода, опциональный автоподъём резерва | Все тесты AC T22 зелёные (`DEFAULT_CODEX_RESTART_PCT` удалён, стоимость/рекомендация/адаптация резерва, `CR_CODEX_INTERRUPT_AFTER_SEC`); `docs/codex.md` сокращён; `./test/run.sh` зелёный | T18 | cc:TODO |
| T07 | `[lane:gate]` `[tdd:required]` Passthrough не-сессионных подкоманд claude (`auth`, `mcp`, `update`, `stop`, …) — exec напрямую, без pty-супервизора | Все тесты AC T07 зелёные (`stop`/`mcp list` не создают `start:`; `attach`/`agents`/промпт по-прежнему оборачиваются); `./test/run.sh` зелёный | - | cc:TODO |

## Phase 8: Эксплуатация и релиз (Эпик E)

Purpose: закрыть техдолг (лог без ротации, 4 незарелизенных коммита) и обновить документацию под новую модель после эпиков A/B.

| Task | Содержание | DoD | Depends | Status |
|------|------|-----|---------|--------|
| T23 | `[lane:gate]` `[tdd:required]` Ротация лога (`CR_LOG_MAX_BYTES`/`CR_LOG_KEEP`), безопасная для конкурентных писателей | Все тесты AC T23 зелёные (ротация при старте, отсутствие ротации ниже лимита); `./test/run.sh` зелёный | - | cc:TODO |
| T25 | `[lane:fast]` `[tdd:skip:docs-only]` Документация после эпиков A/B: `docs/context-restart.md`/`docs/codex.md`/`docs/how-it-works.md`/`docs/troubleshooting.md` без устаревших Caveats | `grep -n "grew last\|left untouched\|Caveats" docs/` пусто; ссылки/якоря между документами валидны | T02, T04, T05, T08, T09 | cc:TODO |
| T24 | `[lane:release]` `[tdd:skip:release-prep]` CHANGELOG для 4 незарелизенных коммитов + всех вошедших в релиз задач бэклога, `CR_VERSION`, тег, GitHub release, homebrew tap формула | `CHANGELOG.md` содержит запись на каждый коммит/задачу; version-тест зелёный; тег и release созданы, формула в tap обновлена (без `brew install/upgrade` на машине пользователя — память проекта); `./test/run.sh` зелёный | выполненные P0-задачи | cc:TODO |
| T26-live | `[lane:fast]` `[tdd:skip:optional-manual]` `test/run.sh --live-codex`: опциональный чек-лист из T15 как скрипт с подтверждением и очисткой сирот | Скрипт запускается только с явным подтверждением, тратит квоту осознанно, гарантированно убивает группы процессов после | T15, T26 | cc:TODO |

---

## Следующий шаг

Сначала T27 (Phase 0): она не трогает ни `Controller`, ни
`TranscriptWatcher`, поэтому не конфликтует с Phase 1 и может идти до неё или
рядом с ней. Внутри T27 порядок обязателен: `Screen` в супервизор →
`find_agent_rows` по сетке → `SubagentRegistry` → `AgentOverlay` — каждый шаг
тестируется предыдущим.

После неё Phase 1 — семь задач с общими инвариантами
(identity → path-bound → handoff), лучше вести последовательно одной
сессией, а не параллельным breezing — порядок T01→T26→T02→T04→T05/T10/T11→T06
важен для того, чтобы тесты каждой задачи опирались на инфраструктуру
предыдущей.

Новая сессия: `claude`
Первый ввод: `/harness-work T27`
Почему: T27 — единственная задача, отвечающая на вопрос «куда уходит квота
прямо сейчас», и её тестовая инфраструктура (эмулятор экрана в супервизоре,
фейк с деревом субагентов) переиспользуется в AC T14. Phase 1 после неё
по-прежнему идёт последовательно одной сессией: её задачи меняют одни и те же
функции контроллера, и параллельный запуск увеличит риск конфликтов правки
одного файла (`claude-retrier.sh` однофайловый).

Альтернатива для длинной сессии без пересборки контекста между T01…T06:
`ENABLE_PROMPT_CACHING_1H=1 claude`, первый ввод `/harness-loop T01`.
