param([Parameter(Mandatory=$true)][string]$MsiPath)
$ErrorActionPreference = 'Stop'
$msi = (Resolve-Path $MsiPath).Path
$dist = Split-Path $msi
$data = Join-Path $env:ProgramData 'tg-ws-proxy'
$exe = Join-Path $env:ProgramFiles 'Flowseal\TG Proxy\tg-ws-proxy.exe'
$ruleNames = @('TG Proxy (программа)', 'TG Proxy TCP порт')
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
function Assert-Firewall {
    foreach ($name in $ruleNames) {
        $rules = @(Get-NetFirewallRule -DisplayName $name)
        if ($rules.Count -ne 1) { throw "Expected one firewall rule: $name" }
        $rule = $rules[0]
        if ($rule.Enabled -ne 'True' -or $rule.Direction -ne 'Inbound' -or
            $rule.Action -ne 'Allow' -or $rule.Profile -ne 'Any') {
            throw "Firewall rule must allow inbound traffic on all profiles: $name"
        }
        if (($rule | Get-NetFirewallAddressFilter).RemoteAddress -ne 'Any') {
            throw "Firewall remote scope must be Any: $name"
        }
        $application = $rule | Get-NetFirewallApplicationFilter
        $ports = $rule | Get-NetFirewallPortFilter
        if ($name -eq 'TG Proxy (программа)') {
            if ($application.Program -ne $exe -or $ports.LocalPort -ne 'Any') {
                throw 'Program rule must match the installed EXE without a port restriction'
            }
        } elseif ($application.Program -ne 'Any' -or $ports.LocalPort -ne "$port" -or
                  $ports.Protocol -notin @('TCP', '6')) {
            throw 'Port rule must match TCP PROXYPORT without an application restriction'
        }
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
    Assert-Firewall
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
foreach ($name in $ruleNames) {
    if (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue) {
        throw "Firewall rule survived uninstall: $name"
    }
}
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
Write-Output 'PASS: MSI install/start/stop/recovery/uninstall, Flowseal\TG Proxy path, dual TCP bind, both firewall rules, config preservation; standalone lifecycle'
