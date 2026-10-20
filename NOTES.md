# Исходник, решение и допущения

База: Flowseal/tg-ws-proxy, upstream `307a384` (полный clone, не shallow), версия `1.11.2`, MIT, Copyright (c) 2026 Flowseal. Этот upstream существенно больше старого однофайлового прокси из описания задания.

## Запуск и поток данных

- `pyproject.toml`: CLI `tg-ws-proxy = proxy.tg_ws_proxy:main`; GUI entry points `windows:main`, `linux:main`, `macos:main`. Прямой запуск `python -m proxy.tg_ws_proxy` и `python proxy/tg_ws_proxy.py` тоже работает.
- `proxy/config.py`: dataclass `ProxyConfig`, общий singleton `proxy_config`, список переадресаций DC, настройки H2/CF/worker/fake TLS, обновление CF-доменов фоновым потоком. До правок `host='127.0.0.1'`, порты 1443, случайный 16-байтный секрет, redirects DC2/DC4 на 149.154.167.220.
- CLI до правок не читал JSON: аргументы напрямую записывались в singleton, затем `asyncio.run(_run())`. Аргументы: `--host`, `--port`, `--secret`, повторяемый `--dc-ip DC:IPv4` (без значения — пустой redirects), `-v/--verbose`, `--log-file`, `--log-max-mb`, `--log-backups`, `--buf-kb`, `--pool-size`, повторяемые `--cfproxy-domain` и `--cfproxy-worker-domain`, `--no-h2` (скрытый совместимый `--cfproxy-h2-media`), `--no-cfproxy`, `--no-secure`, `--fake-tls-domain`, `--force-test-dc`, `--proxy-protocol`.
- `_run`: guard Windows event loop, сброс pools/backoff, H2 pool, выбор CF-доменов, `asyncio.start_server`, лог старта, прогрев WS/worker pools. Один asyncio Server может владеть несколькими сокетами. Watchdog перезапускает listener, статистика раз в минуту. Клиенты отслеживаются и отменяются при stop/cancel; pools закрываются.
- Клиент: `TCP -> optional PROXY v1 -> optional fake TLS -> obfuscated MTProto init -> AES CTR -> WS pool -> bridge`. Если pool недоступен, `bridge.do_fallback` выбирает H2 для media, worker/CF WS, TCP fallback по существующим условиям. `pool.py` управляет сроком жизни, пополнением и backoff; `raw_websocket.py` реализует RFC6455 framing; `bridge.py` — MTProto splitter и AES relay; `_aes.py` — cryptography/OpenSSL shim.
- `cf_h2.py`/`h2_transport.py`: multiplex HTTP/2, lanes/channels, ограничения памяти/inflight, контроль потока, replay/recovery и backpressure. Логику этих транспортов не переписывали.
- `fake_tls.py`: проверка ClientHello, ee-протокол и TLS records, masking relay. `event_loop.py`: восстановление self-pipe Proactor на Windows. `balancer.py`, `stats.py`, `network_debug.py`, `utils.py` — домены, счётчики, диагностика, TLS trust/URI и сетевые константы.
- Tray платформы запускают то же ядро в фоне через `utils/tray_common.py`, хранят собственный пользовательский/portable JSON и лог, делают update checks. `ui/settings*`, `ui/ctk_*`, `ui/i18n` — форма настроек, theme, tooltip, переводы. GUI имеет старый IPv4-only валидатор host; MSI использует отдельный headless entry point, GUI в его сборку не входит. Его собственный loopback-default намеренно сохранён.
- `utils/update_check.py`, `linux_update.py`, `windows_update.py`, `diagnostics.py`, `win32_theme.py` обслуживают desktop-приложения. Исходный `.github/workflows/build.yml` и `packaging/{windows,linux,macos}.spec` собирают GUI для разных платформ; новый workflow от них независим.

## Какие ссылки печатал upstream

Одна `tg://proxy?server=HOST&port=PORT&secret=dd<SECRET>`; при `--fake-tls-domain` вместо неё одна `secret=ee<SECRET><DOMAIN_ASCII_HEX>`. Upstream печатал секрет и ссылки в общий лог. Для `0.0.0.0` функция `get_link_host` выбирала исходящий IPv4 через UDP connect; прочие hosts подставлялись буквально, без IPv6-скобок. DomainCensorFilter мог портить DNS-имя в ссылке.

Теперь строится ссылка для каждого host + public_host, IPv6 в скобках, зоны URI-escaped; dd/ee семантика прежняя. Wildcards печатаются буквально и помечены в README как непригодные адреса клиента. Нет определения внешнего адреса через сторонний endpoint. Ссылки доступны в консоли и `--print-links`; файловые логи их исключают, отдельная строка Secret удалена.

## Варианты и принятое решение

1. **Список hosts штатного asyncio.start_server**: минимум diff, отдельные v4/v6 sockets с V6ONLY, общий stop/watchdog. Выбран.
2. Ручной server на каждый адрес: больше кода для rollback, остановки и watchdog. Не требуется.
3. Один dual-stack IPv6 socket: хорошо для wildcard, но не покрывает произвольный набор конкретных IPv4/IPv6 и зависит от Windows socket semantics. Не выбран.

Новый `proxy/listeners.py` — общий parser/formatter/link builder; `configure()` — загрузка JSON с валидацией и CLI precedence; `windows_service.py` — SCM host на pywin32. MSI использует ServiceInstall/ServiceControl, util ServiceConfig recovery и FirewallException. Никаких NSSM и внешних service wrappers.

Запрошенная реализация выполнена по предоставленному ТЗ без отдельного интерактивного согласования дизайна, согласно прямому указанию исполнителю не задавать вопросы. Отдельный writing-plans не применялся; этот файл фиксирует выбранную архитектуру и допущения. Субагенты не запускались.

## Контракт JSON и допущения (questions)

- `host`: непустая строка через запятую или JSON list строк; IP/DNS, без порта; дубликаты убираются. `public_host`: строка, допускается несколько через запятую; только для ссылок. `port`: целое 1–65535; `secret`: 32 hex. Остальные ключи совпадают с CLI dest (`no_h2`, `dc_ip`, `pool_size`, ...), неизвестные ключи отклоняются. CLI overrides JSON, включая замену списка dc_ip.
- IPv6 включён на Windows сервере; если нет, администратор явно выбирает IPv4-only host. Недоступный конкретный адрес — ошибка, не частичный успех. Listener port 0 доступен только внутреннему API/тестам и выбирается общий на все sockets.
- Внешний и внутренний порт NAT совпадают; параметр public_port не вводился. public_host не привязывается к интерфейсу Windows.
- Исходящие IPv4 redirects сохранены. Опциональный `--ipv6` / `ipv6: true` разрешает явно заданный IPv6 в dc_ip; нет догадок об IPv6-адресах DC и автоматического перевода CF/TCP маршрутов на IPv6. DNS-based transports сохраняют поведение upstream.
- Служба LocalSystem, startup auto, restart 5 секунд, ProgramData защищён ACL в MSI и в самом service host (SYSTEM и Administrators). Ошибка после bind/restart поднимается до service host и приводит к ненулевому завершению для SCM recovery. Нормальная остановка закрывает listener/clients/pools.
- Файлы пользователя в ProgramData сохраняются при uninstall и upgrade. Полная очистка — отдельная команда администратора из README. MSI firewall управляет выбранным при установке PROXYPORT; после изменения JSON порта администратор меняет существующее правило.
- Версия service-пакета/EXE 1.11.3, неизменяемый UpgradeCode E83E6106-BDC7-47E2-9655-4249DDD7E664. Версия GUI upstream остаётся 1.11.2. Подпись кода не включена: сертификат не предоставлен.

## Первичные справочники

Проверены документация [pywin32 ServiceFramework](https://github.com/mhammond/pywin32/blob/main/win32/Lib/win32serviceutil.py), [WiX ServiceConfig](https://docs.firegiant.com/wix/schema/util/serviceconfig/), [FirewallException](https://docs.firegiant.com/wix/schema/firewall/firewallexception/) и [PermissionEx](https://docs.firegiant.com/wix/schema/wxs/permissionex/). Это справка по API, не свидетельство успешной Windows-сборки.
