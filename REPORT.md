# Отчёт исполнителя

Реализация подготовлена локально. Windows EXE/MSI **не собраны и не проверены на Windows**: Actions не запускались, push/публикаций не было. Для выпуска нужен успешный Windows pipeline, включая smoke установки и удаления.

## Что изменено

- Сохранён полный clone Flowseal/tg-ws-proxy: база `307a384`, 336 исходных коммитов, не shallow. Наши изменения фиксируются отдельным локальным коммитом поверх базы.
- В существующем ядре изменены `proxy/config.py` и `proxy/tg_ws_proxy.py`; добавлен небольшой `proxy/listeners.py`. Протоколы MTProto/AES/WS/H2 и GUI не переписаны.
- `--host` и JSON `host`: строка через запятую / JSON-массив, по умолчанию `0.0.0.0,::`. Один asyncio Server владеет отдельными IPv4/IPv6 сокетами. Все буквальные адреса проверяются после bind; недоступный адрес приводит к откату, даже если asyncio попыталось его пропустить.
- Ссылки для всех hosts и дополнительных `--public-host` / `public_host`, IPv6 в скобках, сохранены dd и ee режимы. NAT-адрес не используется для bind. `--print-links` работает без запуска сети. Секреты и ссылки исключены из файлового лога CLI/службы.
- `--config`: проверка JSON/типов/портов/секрета, CLI имеет приоритет. `--ipv6` / `ipv6` разрешает явно указанные IPv6 DC redirects; IPv4 defaults и fallback оставлены прежними.
- `windows_service.py`: pywin32, SCM start/stop/shutdown, auto install/start/stop/remove команды, обработка stop из другого потока, ненулевое завершение при сбое для SCM recovery. Конфиг и ротируемый лог в ProgramData, ACL SYSTEM/Administrators, секрет генерируется только при первом runtime-запуске.
- `packaging/service.spec`: headless PyInstaller onefile `tg-ws-proxy.exe`, AMD64 Python выбирает Actions, MIT LICENSE включён. Версия EXE/MSI 1.11.3. WiX v4 `packaging/msi/Package.wxs`: Program Files, ServiceInstall/ServiceControl, restart actions, TCP firewall rule, удаление службы/правила, постоянный UpgradeCode.
- Workflow `build-msi.yml`: manual dispatch, Windows/Python 3.11 x64, зависимости, полный pytest, PyInstaller, WiX 4.0.6 + Firewall/Util extensions, MSI, Windows smoke, артефакт `tg-ws-proxy-x64.msi`. Windows smoke проверяет также restart после принудительного завершения, сохранность конфига, отсутствие секрета в логе и отдельный standalone lifecycle.
- `README-RU.md`: установка, JSON, NAT, ссылки, смена порта и правила, служба, лог, удаление. `NOTES.md`: устройство исходника, аргументы, архитектурный выбор и допущения.

## Проверки на macOS

Команды ниже запускались из папки задания. Окружения целиком находятся здесь: `.venv` (Python 3.14.8) и `.venv311` (Python 3.11.17). Системный Python и файлы за пределами разрешённых папок не изменялись. Для двух upstream GUI-import тестов установлены customtkinter/Pillow и реальные локальные Tk-библиотеки из Homebrew bottles с проверкой SHA256; GUI и генерация изображений не запускались.

| Проверка | Команда / настоящий результат |
| --- | --- |
| Полный pytest, Python 3.14 | `.venv/bin/python -m pytest repo/tests -q --tb=short`: **279 passed, 14 skipped, 459 subtests passed in 17.26s**. Пропуски — платформенные Windows/Linux проверки; они не считаются проверенными на macOS. |
| Новые тесты, Python 3.11 | `.venv311/bin/python -m pytest repo/tests/test_multibind.py repo/tests/test_packaging.py -q`: **33 passed in 0.53s** (pytest 9.1.1). |
| Реальный CLI, Python 3.11 | `.venv311/bin/python repo/tests/smoke_cli.py`: `TCP connect 127.0.0.1:59098: OK`; `TCP connect ::1:59098: OK`; `CLI SIGINT shutdown: exit 0`. Redirects/pools/CF отключены; к Telegram smoke не подключался. |
| Python syntax | `python -m py_compile` для изменённых Python, service.spec и service_version.txt: exit 0. |
| Ruff изменённых Python | `.venv/bin/ruff check ...`: **All checks passed!** |
| YAML/XML | `yaml.safe_load(build-msi.yml)` и `ElementTree.parse(Package.wxs)`: **Workflow YAML and WiX XML parse: OK**. Также 3 portable packaging contract tests в полном pytest. Это не MSI build. |
| PowerShell | Parser.ParseFile для `tests/windows-msi-smoke.ps1`: **PowerShell syntax OK**. WinAPI-команды этого сценария на Mac не выполнялись. |
| LICENSE | Сравнение с `git show 307a384:LICENSE`: совпадение байт-в-байт; SHA256 `2a98256df06052c3b132cf522e356da90ade2f749b6f7435f7cdafd1d9123fa2`. |
| История / diff | `git rev-parse --is-shallow-repository`: **false**; `git rev-list --count 307a384`: **336**; `git diff --check`: exit 0. |

Логи команд: `../.scratch/evidence/`. Общий `verify.sh` завершился с exit 0: **279 passed, 14 skipped, 459 subtests passed in 14.51s**, оба CLI TCP connect на порту 63576 — OK, SIGINT shutdown — exit 0. Полный вывод в `../.scratch/evidence/verify-py314.txt`. В скрипте compile → полный pytest → запуск реального CLI → diff check. Для повторения:

```sh
source .venv/bin/activate
python3 -m pytest repo/tests -q
PYTHON="$PWD/.venv/bin/python" bash repo/verify.sh
```

## Обнаруженная нестабильность upstream на Python 3.11

Полный набор под Python 3.11 здесь не подтверждён зелёным. Были ошибки коротких таймаутов и зависания отмены в `tests/test_h2_transport.py`; один полный прогон дал `4 failed, 276 passed, 14 skipped, 458 subtests passed in 50.06s`, другие остановлены Ctrl-C после зависания. Параллельный запуск наборов усугублял ситуацию; последовательный запуск и pytest 8.4.2 проблему полностью не устранили.

Для сравнения извлечён **чистый** upstream `307a384` в `../.scratch/upstream`, без наших правок. Последовательный `pytest .../upstream/tests/test_h2_transport.py` тоже получил failure `test_body_tail_does_not_wait_for_unrelated_long_polls` и был прерван после зависания: `1 failed, 2 passed in 42.93s`. Отдельный upstream `test_busy_channel_recovers_old_request_despite_newer_replies` прошёл (`1 passed in 1.01s`). Это свидетельство нестабильности исходных timing/cancellation тестов в данном окружении, а не доказанная конкретная причина. `cf_h2.py`, `h2_transport.py` и исходные тесты не менялись.

Windows workflow сохраняет полный pytest перед сборкой; при воспроизведении этой проблемы сборка будет остановлена. Нужно оценить результат именно Windows/Python 3.11, затем при необходимости отдельно диагностировать исходный H2 transport. Таймауты не увеличивались, тесты не исключались.

## Что пока не проверено (blockers)

1. PyInstaller на Windows AMD64 и фактическая компоновка pywin32/certifi/cryptography в onefile.
2. Полная компиляция/валидация MSI WiX, установка, SCM lifecycle/recovery, ACL и firewall на реальном Windows, корректное удаление/upgrade. Локальная попытка WiX 4.0.6 на Mac выдала предупреждение `The WiX Toolset only supports Windows` и ошибки Windows path validation; успешной сборкой это не считается (`../.scratch/evidence/wix-compile.txt`).
3. Actions не запускались по запрету внешних действий. Руководителю нужно разместить подготовленный commit в своём репозитории и вручную запустить workflow. До зелёного build + smoke артефакт нельзя считать готовым к установке клиенту.
4. Реальный MikroTik/NAT/IPv6 маршрут, доменные GPO, подключение Telegram-клиента и внешние Telegram/DC endpoints не проверялись. Здесь проверены локальные TCP, формат ссылок и upstream unit/integration suite.

## Допущения и лицензия

Внешний/внутренний NAT-порт одинаков; ProgramData-конфиг и лог сохраняются после uninstall; GUI upstream — отдельный продукт; IPv6 DC выбирает администратор, автоматическая карта IPv6 DC не добавлялась. Точные решения описаны в NOTES и README. Вопросы в ходе работы не задавались.

Лицензия оригинала **MIT**, автор **Flowseal**, Copyright (c) 2026 Flowseal. LICENSE не изменён, включён в EXE и MSI. Сертификат подписи не предоставлен; подпись в новой сборке не настроена.
