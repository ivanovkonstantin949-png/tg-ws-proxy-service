# Отчёт исполнителя — доработка, круг 1

Замечания руководителя исправлены локально. Push, сообщения и запуск Actions не выполнялись. Windows EXE/MSI не собраны и не проверены на Windows: для выпуска требуется успешный workflow со smoke установки/удаления.

## Итоговая реализация

Полный clone Flowseal/tg-ws-proxy сохранён: upstream `307a384`, 336 исходных коммитов, shallow=false. Первый локальный коммит `4e24407` добавляет multibind, IPv6, NAT-ссылки, JSON-конфиг, Windows-службу, PyInstaller/WiX и проверки. Текущие исправления оформлены следующим отдельным локальным коммитом.

- `host`: список через запятую / JSON-массив, default `0.0.0.0,::`; проверяется bind каждого буквального адреса, при ошибке — откат. Ссылки под каждый адрес и `public_host`, IPv6 в скобках; `--print-links` работает офлайн. Исходящий IPv6 включается явно. Протоколы upstream и GUI не переписывались.
- `windows_service.py`: pywin32, install/start/stop/remove, LocalSystem, автоматический запуск, recovery через 5 секунд. Данные **оставлены** в `%ProgramData%\tg-ws-proxy`: `config.json`, `log.txt`, ротация и ACL SYSTEM/Administrators. Секрет создаётся при первом запуске и не выводится в лог. Конфиг/лог сохраняются после uninstall.
- MSI: точный путь `C:\Program Files\Flowseal\TG Proxy` через вложенные Directory `Flowseal` → `TG Proxy` под `ProgramFiles64Folder`. GUID компонентов с изменившимися файловыми путями обновлены. Версия 1.11.3 и постоянный UpgradeCode `E83E6106-BDC7-47E2-9655-4249DDD7E664` сохранены. Явная Codepage=1251 поддерживает русские имена правил; атрибут описан в [схеме Package](https://docs.firegiant.com/wix/schema/wxs/package/).
- **Два отдельных правила**: `TG Proxy (программа)` — Program=`[#ProxyExe]`, без Port/Protocol; `TG Proxy TCP порт` — Port=`[PROXYPORT]`, Protocol=tcp, без Program. Оба Scope=any, Profile=all, IgnoreFailure=no, принадлежат компоненту службы и удаляются с ним. Семантика атрибутов сверена с [FirewallException](https://docs.firegiant.com/wix/schema/firewall/firewallexception/).
- Windows smoke проверяет новый путь EXE, оба правила: количество, Enabled/Allow/Inbound, все профили, Any remote scope, программу без порта и TCP-порт без программы; после удаления проверяет отсутствие обоих. Сохранены проверки dual TCP, install/start/stop/remove, recovery, ProgramData, сохранности конфига и отсутствия секрета в логе.
- Actions: Windows/Python 3.11 x64, PyInstaller onefile, WiX 4.0.6 + Firewall/Util, MSI и smoke, артефакт `tg-ws-proxy-x64.msi`. Шаг pytest ограничен **5 минутами**; pytest-timeout 2.4.0 ограничивает каждый тест **30 секундами**, method=thread завершает зависший процесс с ошибкой. `verify.sh` использует тот же файл аргументов.
- README-RU обновлён: точная папка, два правила, смена TCP-порта, ссылки, ProgramData, служба/лог, удаление и проверка отсутствия правил. NOTES фиксирует архитектуру и допущения.

## Исключённые upstream-тесты

Шесть подтверждённых нестабильных тестов перечислены точными node ID в `tests/ci-pytest-args.txt`, первые пять — класс `tests/test_h2_transport.py::H2WireTest`:

1. `test_body_tail_does_not_wait_for_unrelated_long_polls`
2. `test_busy_channel_recovers_old_request_despite_newer_replies`
3. `test_idle_poll_preserves_slot_for_new_overdue_request`
4. `test_obfuscated_clients_preserve_packets_through_full_h2_fallback`
5. `test_normal_long_poll_survives_six_seconds_and_delivers_late_reply`
6. `tests/test_cf_h2.py::HttpMultiplexTest::test_unhelpful_replies_do_not_cause_unbounded_recovery`

Первые четыре падали/зависали в прошлом круге на Python 3.11; ошибка body-tail воспроизводилась и на чистом upstream. Дополнительный прогон текущего круга через PowerShell выявил ещё два H2 timing-сбоя: `0.01434299999527866 not greater than or equal to 0.015` и `replay_requests: 2 != 1` (лог `revision1-workflow-pwsh311-four.txt`, до добавления этих двух исключений: 2 failed, 274 passed, 14 skipped, 4 deselected). Весь остальной H2 и **все новые тесты** остаются включены. Production H2 и его исходные тесты не менялись. Это ограничение объёма CI-проверки, а не исправление upstream transport.

## Повторная локальная проверка

macOS, окружения внутри папки задания: `.venv311` Python 3.11.17 и `.venv` Python 3.14.8, pytest 9.1.1. Все результаты ниже получены в этом круге. Логи: `../.scratch/evidence/revision1-*`.

| Проверка | Команда и настоящий результат |
| --- | --- |
| CI-набор, Python 3.11 + реальный CLI | `PYTHON="$PWD/.venv311/bin/python" bash repo/verify.sh`: **274 passed, 14 skipped, 6 deselected, 456 subtests passed in 9.51s**; `TCP connect 127.0.0.1:50916: OK`; `TCP connect ::1:50916: OK`; `CLI SIGINT shutdown: exit 0`. `revision1-verify311.txt`. |
| CI-набор, Python 3.14 + реальный CLI | `PYTHON="$PWD/.venv/bin/python" bash repo/verify.sh`: **274 passed, 14 skipped, 6 deselected, 456 subtests passed in 8.75s**; оба TCP connect на порту 51327 — **OK**, SIGINT exit 0. `revision1-verify314.txt`. |
| Все новые тесты, Python 3.11 | `.venv311/bin/python -m pytest repo/tests/test_multibind.py repo/tests/test_packaging.py -q --timeout=30 --timeout-method=thread`: **34 passed in 0.15s**. Включены IPv6/NAT-ссылки, JSON/CLI precedence, dual bind, откат, ProgramData/конфиг/лог, XML/YAML и точный список исключений. `revision1-newtests311-final.txt`. |
| Полный набор без исключений | `.venv/bin/python -m pytest repo/tests -q --timeout=30 --timeout-method=thread --tb=short`: **1 failed, 279 passed, 14 skipped, 459 subtests passed in 15.88s**. Упал upstream `test_busy_channel_recovers_old_request_despite_newer_replies`: `AssertionError: 3 not greater than 3`. Этот пункт **не пройден**; он входит в перечисленные исключения. `revision1-full314.txt`. |
| Защита от зависания | Временный тест со sleep(10), pytest timeout=1/thread: **Timeout probe: expected failure exit 1; killed sleeping test in 3.48s (limit 1s)**, внешний subprocess timeout=8. Временный исходник удалён. `revision1-timeout-probe.txt`. |
| Python syntax и diff | `verify.sh`: compileall proxy/windows_service/tests, py_compile service.spec/service_version.txt и `git diff --check`, exit 0. |
| YAML/XML | Четыре portable packaging-теста проходят: вложенный путь, две разные FirewallException, ServiceInstall/ServiceControl, recovery, постоянный UpgradeCode, YAML workflow и таймаут/исключения. Это **не** компиляция MSI. |
| PowerShell syntax | `pwsh` Parser.ParseFile: **PowerShell syntax OK: MSI smoke and workflow test step**, exit 0. `revision1-powershell.txt`. Сам smoke на Mac не запускался. |
| Аргументы через PowerShell | Команда тестового шага с добавленным `--collect-only`: **288/294 tests collected (6 deselected) in 0.25s**, exit 0. Подтверждено, что PowerShell передаёт файл аргументов с `@` буквально. `revision1-workflow-collect-pwsh.txt`. |
| Lint | `.venv/bin/ruff check repo/tests/test_packaging.py`: **All checks passed!** `revision1-ruff.txt`. |
| История и лицензия | `git rev-parse --is-shallow-repository`: **false**; `git rev-list --count 307a384`: **336**. LICENSE байт-в-байт совпадает с `git show 307a384:LICENSE`, SHA256 `2a98256df06052c3b132cf522e356da90ade2f749b6f7435f7cdafd1d9123fa2`. |
| README | Прочитан повторно; старые пути EXE и имя одиночного правила в README, smoke, тестах и workflow отсутствуют. |

14 пропусков — платформенные upstream Windows/Linux тесты; их результаты не считаются проверенными на macOS. Smoke соединяется только с loopback, eager upstream pools/DC/CF отключены. Реальные Telegram-клиенты и NAT здесь не проверялись.

## Что проверит только Windows (blockers)

1. PyInstaller AMD64, полная компиляция и валидация MSI WiX, установка в путь с пробелом, ServiceInstall/ServiceControl, ACL и recovery.
2. Фактическое создание двух правил Windows Firewall и удаление обоих вместе со службой/EXE при uninstall. Подготовленный Windows smoke проверяет это автоматически; локальная XML-проверка не заменяет исполнение.
3. Руководителю нужно перенести локальные коммиты в свой репозиторий и запустить workflow. Push и запуск Actions исполнителем не делались; бинарного MSI пока нет. Также требуется проверка MikroTik/NAT, маршрутизации IPv6 и доменных GPO в окружении клиента.

## Допущения и лицензия

Данные оставлены в `%ProgramData%\tg-ws-proxy`; после удаления MSI конфиг/логи сохраняются. Внутренний и внешний NAT-порты совпадают. GUI upstream — отдельное приложение. IPv6 DC выбирает администратор. Вопросы по ходу не задавались.

Оригинал: **MIT**, автор **Flowseal**, Copyright (c) 2026 Flowseal. LICENSE сохранён и включён в EXE/MSI. Подпись кода не настроена, сертификат не предоставлен.
