# kill-port.ps1 - kill ALL processes occupying a port (uvicorn reloader tree + orphan spawn children)
#
# Why (2026-08-03):
#   With `uvicorn --reload`, the reloader parent creates the listen socket, then spawns a
#   server child. `netstat -ano` reports the PID of the socket CREATOR (the reloader parent),
#   not the actual holder. Killing by netstat PID only kills the parent; the spawned child
#   survives as an orphan and keeps LISTENING on the same port - invisible to netstat's PID
#   list, accumulating across restarts. Old taskkill failures on dead PIDs were misreported
#   as "high-privilege process" - all false alarms.
#
# Strategy (three layers, covers everything):
#   1) uvicorn main processes: CommandLine matches `uvicorn ... --port <Port>`
#   2) live descendants of netstat LISTENING PIDs (may be dead creators) - i.e. socket-inheriting orphans
#   3) recursive descendants of all the above (BFS by ParentProcessId)
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/lib/kill-port.ps1 -Port 8010
# Output: CLEAN (port released) or REMAIN: <pid...> (held by another session / elevated process)
#
# NOTE: keep this file ASCII-only (Windows PowerShell 5.1 parses BOM-less .ps1 as ANSI/GBK,
#       UTF-8 Chinese comments break parsing)
param(
    [Parameter(Mandatory = $true)][int]$Port
)

$ErrorActionPreference = 'SilentlyContinue'

# -- 1) collect candidate PIDs --
$all = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine })

# 1a) uvicorn main processes (exact --port <Port> match, avoid matching :80100 etc.)
$uvicornRoots = @($all | Where-Object {
        $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match ('--port\s+' + $Port + '\b')
    } | Select-Object -ExpandProperty ProcessId)

# 1b) port orphans: trailing PID of netstat LISTENING lines (may be dead socket creators);
#     their live children (spawn_main, socket inherited) are the real holders
$listenPids = @((netstat -ano) | Select-String (':' + $Port + '\s') |
        Where-Object { $_.Line -match 'LISTENING' } |
        ForEach-Object { ($_.Line -split '\s+')[-1] } |
        Where-Object { $_ -match '^\d+$' } | Sort-Object -Unique)

# -- 2) build kill set: roots + listen PIDs + BFS descendants --
$kill = New-Object 'System.Collections.Generic.HashSet[int]'
foreach ($id in @($uvicornRoots + $listenPids)) { [void]$kill.Add([int]$id) }

$changed = $true
while ($changed) {
    $changed = $false
    foreach ($p in $all) {
        if ($kill.Contains([int]$p.ParentProcessId) -and -not $kill.Contains([int]$p.ProcessId)) {
            [void]$kill.Add([int]$p.ProcessId)
            $changed = $true
        }
    }
}

# -- 3) kill --
foreach ($id in $kill) {
    Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
}

# -- 4) verify (Get-NetTCPConnection is more reliable than netstat) --
Start-Sleep -Milliseconds 800
$left = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($left.Count -gt 0) {
    $owners = @($left | Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique)
    Write-Output ("REMAIN: " + ($owners -join ' '))
}
else {
    Write-Output "CLEAN"
}
