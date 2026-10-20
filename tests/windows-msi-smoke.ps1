param([Parameter(Mandatory=$true)][string]$MsiPath)
$ErrorActionPreference = 'Stop'
$msi = (Resolve-Path $MsiPath).Path
$dist = Split-Path $msi
$data = Join-Path $env:ProgramData 'tg-ws-proxy'
$exe = Join-Path $env:ProgramFiles 'tg-ws-proxy\tg-ws-proxy.exe'
$config = Join-Path $data 'config.json'
$port = 21443
if ((Test-Path $data) -or (Get-Service TgWsProxy -ErrorAction SilentlyContinue)) {
    throw 'MSI smoke requires a clean test machine without an existing tg-ws-proxy installation/data directory'
}

function Install-Msi([string]$operation, [string]$logName) {
    $process = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @(
        $operation, "`"$msi`"", '/qn', '/norestart', "PROXYPORT=$port", '/L*v',
        "`"$(Join-Path $dist $logName)`"")
    if ($process.ExitCode -notin @(0, 3010)) { throw "MSI failed: $($process.ExitCode)" }
}
function Wait-Running {
    (Get-Service TgWsProxy).WaitForStatus('Running', [TimeSpan]::FromSeconds(45))
}
function Assert-Listeners {
    foreach ($address in @('127.0.0.1', '::1')) {
        $client = [System.Net.Sockets.TcpClient]::new(
            $(if ($address -eq '::1') { [System.Net.Sockets.AddressFamily]::InterNetworkV6 }
              else { [System.Net.Sockets.AddressFamily]::InterNetwork }))
        try {
            $client.ConnectAsync($address, $port).WaitAsync([TimeSpan]::FromSeconds(5)).GetAwaiter().GetResult()
        } finally { $client.Dispose() }
    }
}

# Existing config deliberately disables all eager upstream work in this test.
# The random runtime secret is never printed or included in build artifacts.
New-Item -ItemType Directory -Force $data | Out-Null
python -c "import json,os,pathlib; p=pathlib.Path(os.environ['ProgramData'])/'tg-ws-proxy'/'config.json'; p.write_text(json.dumps(dict(host='127.0.0.1,::1',port=$port,secret=os.urandom(16).hex(),dc_ip=[],pool_size=0,no_cfproxy=True,no_h2=True)),encoding='utf-8')"
if ($LASTEXITCODE) { throw 'Cannot prepare smoke config' }
$originalHash = (Get-FileHash $config).Hash
try {
    Install-Msi '/i' 'msi-install.log'
    Wait-Running
    Assert-Listeners
    if (!(Test-Path $exe)) { throw 'Installed EXE missing' }
    $service = Get-CimInstance Win32_Service -Filter "Name='TgWsProxy'"
    if ($service.StartMode -ne 'Auto') { throw 'Service is not automatic' }
    $rule = Get-NetFirewallRule -DisplayName 'tg-ws-proxy TCP'
    if (($rule | Get-NetFirewallPortFilter).LocalPort -ne "$port") { throw 'Firewall port mismatch' }
    if (!(Test-Path (Join-Path $data 'log.txt'))) { throw 'Service log missing' }
    if ((Get-FileHash $config).Hash -ne $originalHash) { throw 'Install overwrote config' }
    $secret = (Get-Content $config -Raw | ConvertFrom-Json).secret
    if ((Get-Content (Join-Path $data 'log.txt') -Raw).Contains($secret)) { throw 'Secret leaked to log' }
    Stop-Service TgWsProxy
    (Get-Service TgWsProxy).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
    Start-Service TgWsProxy
    Wait-Running
    Assert-Listeners
    # Kill the actual service process (the onefile child), then verify SCM recovery.
    $oldPid = (Get-CimInstance Win32_Service -Filter "Name='TgWsProxy'").ProcessId
    Stop-Process -Id $oldPid -Force
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    do {
        Start-Sleep -Milliseconds 500
        $recovered = Get-CimInstance Win32_Service -Filter "Name='TgWsProxy'"
    } until (($recovered.State -eq 'Running' -and $recovered.ProcessId -ne $oldPid) -or [DateTime]::UtcNow -ge $deadline)
    if ($recovered.State -ne 'Running' -or $recovered.ProcessId -eq $oldPid) { throw 'SCM restart failed' }
    Assert-Listeners
} finally {
    Install-Msi '/x' 'msi-uninstall.log'
}
if (Get-Service TgWsProxy -ErrorAction SilentlyContinue) { throw 'Service survived uninstall' }
if (Get-NetFirewallRule -DisplayName 'tg-ws-proxy TCP' -ErrorAction SilentlyContinue) { throw 'Firewall rule survived uninstall' }
if (Test-Path $exe) { throw 'EXE survived uninstall' }
if ((Get-FileHash $config).Hash -ne $originalHash) { throw 'Uninstall overwrote config' }

# Separate standalone lifecycle; do not mix it with an MSI-managed installation.
$standalone = Join-Path $dist 'tg-ws-proxy.exe'
try {
    & $standalone service install
    if ($LASTEXITCODE) { throw 'Standalone install failed' }
    & $standalone service start
    if ($LASTEXITCODE) { throw 'Standalone start failed' }
    Wait-Running
    Assert-Listeners
    & $standalone service stop
    if ($LASTEXITCODE) { throw 'Standalone stop failed' }
    (Get-Service TgWsProxy).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(30))
} finally {
    & $standalone service remove
    if ($LASTEXITCODE) { throw 'Standalone remove failed' }
}
if (Get-Service TgWsProxy -ErrorAction SilentlyContinue) { throw 'Standalone service survived removal' }
Remove-Item $data -Recurse -Force
Write-Output 'PASS: MSI install/start/stop/recovery/uninstall, dual TCP bind, firewall, config preservation; standalone lifecycle'
