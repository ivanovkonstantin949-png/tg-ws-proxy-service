# tg-ws-proxy: Windows-служба, IPv4 + IPv6

Доработка [Flowseal/tg-ws-proxy](https://github.com/Flowseal/tg-ws-proxy), лицензия MIT, автор Flowseal. Исходный `LICENSE` сохранён. Это отдельная сборка для сервера без GUI.

Теперь один процесс слушает несколько адресов. По умолчанию `0.0.0.0,::` — все IPv4 и IPv6 интерфейсы. Входящий IPv6 не меняет исходящие подключения к Telegram. Пример двух конкретных адресов: `192.168.0.16,2001:db8::16` (IPv6 из примера заменить своим).

## 1. Установка

Нужны Windows x64 с IPv6 и права локального администратора. Python отдельно ставить не требуется. Сначала руководитель должен получить зелёную сборку **Build Windows service MSI** в Actions своего репозитория (`workflow_dispatch`) и скачать артефакт `tg-ws-proxy-x64.msi`.

Откройте PowerShell **от имени администратора** в папке с MSI:

```powershell
msiexec.exe /i .\tg-ws-proxy-x64.msi /qn /norestart
```

Для первого запуска на другом порту добавьте `PROXYPORT=2443`. Установщик размещает EXE в `C:\Program Files\Flowseal\TG Proxy`, регистрирует автозапускаемую службу `TgWsProxy` от LocalSystem, запускает её и создаёт **два отдельных входящих разрешающих правила** во всех профилях Windows Firewall, с областью Any:

- `TG Proxy (программа)` — для установленного EXE, без ограничения порта.
- `TG Proxy TCP порт` — для TCP-порта (по умолчанию 1443, параметр `PROXYPORT`), без привязки к программе.

При падении SCM перезапускает службу через 5 секунд. Доменные GPO могут запрещать локальные правила — это должен проверить сетевой администратор.

## 2. Конфигурация и NAT

При первом запуске служба создаёт `%ProgramData%\tg-ws-proxy\config.json` со случайным секретом. Следующие запуски и переустановка сохраняют файл. Доступ к каталогу после MSI есть у SYSTEM и администраторов.

```powershell
Stop-Service TgWsProxy
notepad "$env:ProgramData\tg-ws-proxy\config.json"
```

Измените существующие поля, **сохранив поле `secret`**:

| Поле | Значение |
| --- | --- |
| `host` | `"192.168.0.16,2001:db8::16"` или `"0.0.0.0,::"`; допустим JSON-массив адресов |
| `port` | TCP-порт, целое число 1–65535 |
| `public_host` | Внешний IP/домен, например `"proxy.example.com"`; добавляет ссылку, не участвует в bind |
| `secret` | Существующие 32 шестнадцатеричных символа; изменение потребует новых ссылок у клиентов |
| `ipv6` | `false` по умолчанию; `true` разрешает явно указанные IPv6-адреса `dc_ip` |

Если IPv6 выключен на сервере, явно задайте `host: "0.0.0.0"`. Невозможность привязать заданный адрес считается ошибкой запуска; прокси не пропускает его молча.

При смене порта измените существующее правило порта `TG Proxy TCP порт` (правило программы менять не требуется):

```powershell
Get-NetFirewallRule -DisplayName 'TG Proxy TCP порт' | Get-NetFirewallPortFilter | Set-NetFirewallPortFilter -LocalPort 2443
Start-Service TgWsProxy
```

На MikroTik настройте проброс **TCP того же порта** внешнего IPv4 на `192.168.0.16`, разрешите его в firewall. Внешний IP за NAT не нужно назначать Windows и вписывать в `host`. Для IPv6 нужен реально назначенный серверу адрес, маршрутизация и разрешение входящего трафика на роутере. `public_host` не настраивает NAT, DNS или роутер. Hairpin NAT для доступа из LAN по внешнему IPv4 настраивается отдельно.

## 3. Ссылки подключения

Офлайн-команда читает конфиг и выводит ссылки в консоль для каждого bind-адреса плюс `public_host`; прокси при этом не запускается:

```powershell
& "$env:ProgramFiles\Flowseal\TG Proxy\tg-ws-proxy.exe" --config "$env:ProgramData\tg-ws-proxy\config.json" --print-links
```

IPv6 в ссылке имеет вид `server=[2001:db8::16]`. Ссылки содержат секрет: передавайте их только своим пользователям, не включайте в отчёты и общие логи. В `log.txt` ссылки и секрет не записываются. Адреса `0.0.0.0` и `[::]` обозначают bind всех интерфейсов и не подходят клиентам: используйте ссылку с конкретным адресом или `public_host`. LAN-клиентам — внутреннюю ссылку, внешним — ссылку с внешним адресом.

Исходящий IPv4 и fallback сохранены. Для явно выбранного IPv6 DC в конфиге укажите `"ipv6": true` и `"dc_ip": ["2:[ВАШ_IPV6_АДРЕС_DC]"]`; либо CLI `--ipv6 --dc-ip '2:[АДРЕС_DC]'`. Адрес DC предоставляет администратор. Флаг не подменяет автоматически адреса всех DC и CF-серверов.

## 4. Служба и лог

```powershell
Get-Service TgWsProxy
Restart-Service TgWsProxy
Get-Content "$env:ProgramData\tg-ws-proxy\log.txt" -Tail 50 -Wait
sc.exe qc TgWsProxy
sc.exe qfailure TgWsProxy
```

Лог ротируется: `log.txt`, `log.txt.1`, `log.txt.2`, примерно по 5 МБ. Ошибки bind/конфига ищите в логе. Изменения конфига вступают в силу после перезапуска. При обновлении MSI оставляйте `PROXYPORT` равным действующему порту и затем проверьте правило `TG Proxy TCP порт`: установщик не читает изменённый JSON для выбора порта правила.

Для отдельного EXE без MSI доступны команды ниже. Не используйте их поверх MSI-установки; самостоятельная установка службы не создаёт правила firewall:

```powershell
.\tg-ws-proxy.exe service install
.\tg-ws-proxy.exe service start
.\tg-ws-proxy.exe service stop
.\tg-ws-proxy.exe service remove
```

## 5. Удаление

```powershell
msiexec.exe /x .\tg-ws-proxy-x64.msi /qn /norestart
```

Также можно удалить через «Установленные приложения». Служба останавливается и удаляется, EXE и оба правила firewall удаляются. Проверка после удаления:

```powershell
Get-Service TgWsProxy -ErrorAction SilentlyContinue
Get-NetFirewallRule -DisplayName 'TG Proxy (программа)', 'TG Proxy TCP порт' -ErrorAction SilentlyContinue
```

Обе команды должны вернуть пустой результат. Конфиг с секретом и логи остаются для переустановки. Если они больше не нужны, **после удаления MSI**:

```powershell
Remove-Item "$env:ProgramData\tg-ws-proxy" -Recurse -Force
```

## Запуск из исходников на macOS/Linux

Из папки `repo`, Python 3.11+, установите зависимости ядра (`certifi`, `cryptography`, `httpx[http2]`), затем:

```sh
python3 -m proxy.tg_ws_proxy --host '127.0.0.1,::1' --public-host proxy.example.com
```

CLI принимает `--config path/to/config.json`, параметры командной строки имеют приоритет. Без сохранённого `secret` консольный запуск создаёт новый секрет при каждом старте. GUI upstream остаётся отдельным приложением со своим прежним конфигом; MSI его не устанавливает.

## Проверка исходников и сборки

Установите `packaging/requirements-service.txt` и `packaging/requirements-test.txt` в виртуальное окружение. `PYTHON=путь/к/python bash verify.sh` проверяет синтаксис, запускает тесты с тем же списком исключений, что и Actions, затем на macOS/Linux проверяет TCP на `127.0.0.1` и `::1`. Список шести нестабильных upstream H2-тестов явно указан в `tests/ci-pytest-args.txt`; все новые тесты остаются включены. Таймаут каждого теста — 30 секунд (завершение процесса при зависании), шаг тестов Actions ограничен 5 минутами. Полный набор без исключений: `python -m pytest tests -q --timeout=30 --timeout-method=thread`.

Windows smoke в Actions проверяет точный путь EXE, оба отдельных правила (программа без порта и TCP-порт без программы), удаление обоих правил, службу и её восстановление. Локальная проверка YAML/XML не заменяет этот Windows smoke.
