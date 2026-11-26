#requires -Version 7.0
<#
.SYNOPSIS
    CTF 工具链体检：读 registry.json，逐项验证"能不能真的用"。

.DESCRIPTION
    状态口径：
      OK    路径存在 / MCP 握手成功且工具数达标
      DOWN  服务没开（连接被拒、IDA 未运行）—— 不是故障
      FAIL  路径缺失、探针报错、工具数低于 min_tools —— 真故障
      SKIP  标了不检查的条目

    退出码 = FAIL 数（DOWN 不计）。

.EXAMPLE
    pwsh -File D:\CTF\Toolchain\doctor.ps1
    pwsh -File D:\CTF\Toolchain\doctor.ps1 -Json
#>
[CmdletBinding()]
param(
    [switch]$Json,
    [string]$Registry = (Join-Path $PSScriptRoot 'registry.json')
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$ProbeScript = Join-Path $Root 'scripts\mcp_probe.py'
$WslDistro = 'Ubuntu-26.04'

function ConvertTo-WslPath {
    param([string]$WinPath)
    if ($WinPath -match '^([A-Za-z]):[\\/](.*)$') {
        return '/mnt/' + $Matches[1].ToLower() + '/' + ($Matches[2] -replace '\\', '/')
    }
    return $WinPath
}

function Get-JsonFromText {
    param([string]$Text)
    if (-not $Text) { return $null }
    foreach ($line in ($Text -split "`r?`n")) {
        $t = $line.Trim()
        if ($t.StartsWith('{')) {
            try { return $t | ConvertFrom-Json } catch { }
        }
    }
    return $null
}

function Test-Tcp {
    param([string]$Target, [int]$TimeoutMs = 600)
    try {
        $u = [uri]$Target
        $client = [System.Net.Sockets.TcpClient]::new()
        try {
            $task = $client.ConnectAsync($u.Host, $u.Port)
            if (-not $task.Wait($TimeoutMs)) { return $false }
            return $client.Connected
        }
        finally { $client.Dispose() }
    }
    catch { return $false }
}

function Get-CallTarget {
    param($Entry)
    if ($Entry.entry) { return $Entry.entry }
    return $Entry.exec
}

function Invoke-Capture {
    param([string]$File, [string[]]$Arguments)
    try {
        $out = & $File @Arguments 2>&1 | Out-String
        return @{ code = $LASTEXITCODE; out = $out }
    }
    catch {
        return @{ code = -1; out = $_.Exception.Message }
    }
}

function Test-Entry {
    param($Entry)

    $row = [ordered]@{
        name = $Entry.name; kind = $Entry.kind; side = $Entry.side
        status = 'FAIL'; detail = ''
    }

    # ---- gui: 只看路径
    if ($Entry.kind -eq 'gui') {
        $target = Get-CallTarget -Entry $Entry
        if (Test-Path -LiteralPath $target) { $row.status = 'OK'; $row.detail = 'launcher present' }
        else { $row.detail = "missing: $target" }
        return [pscustomobject]$row
    }

    # ---- cli: 路径 + 可选自检
    if ($Entry.kind -eq 'cli') {
        $target = Get-CallTarget -Entry $Entry
        if (-not (Test-Path -LiteralPath $target)) {
            $row.detail = "missing: $target"
            return [pscustomobject]$row
        }
        if ($Entry.probe -and $Entry.probe.args) {
            $r = Invoke-Capture -File $target -Arguments @($Entry.probe.args)
            $first = ($r.out -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
            if ($r.code -eq 0) { $row.status = 'OK'; $row.detail = "$first" }
            else { $row.detail = "probe rc=$($r.code): $first" }
        }
        else { $row.status = 'OK'; $row.detail = 'path only' }
        return [pscustomobject]$row
    }

    # ---- mcp
    if ($Entry.kind -eq 'mcp') {
        # 有 http 依赖的先看端口：服务没开 = DOWN，不该算 FAIL
        if ($Entry.depends -and $Entry.depends.http) {
            if (-not (Test-Tcp -Target $Entry.depends.http)) {
                $row.status = 'DOWN'
                $row.detail = "service not listening: $($Entry.depends.http)"
                return [pscustomobject]$row
            }
        }
        if ($Entry.side -like 'wsl:*') {
            $args = @('-d', $WslDistro, '-u', $Entry.user,
                'python3', (ConvertTo-WslPath $ProbeScript), '--http', $Entry.url)
            if ($Entry.token_file) { $args += '--token-file'; $args += $Entry.token_file }

            # WSL 发行版空闲会自关机：先唤醒，再探；DOWN 就重试一次。
            for ($attempt = 1; $attempt -le 2; $attempt++) {
                if ($attempt -gt 1) { Start-Sleep -Seconds 3 }
                try { & wsl -d $WslDistro -u $Entry.user -- true 2>&1 | Out-Null } catch { }
                $r = Invoke-Capture -File 'wsl' -Arguments $args
                $j = Get-JsonFromText -Text $r.out
                if ($j -and $j.ok) { break }
                if ($j -and $j.state -ne 'down') { break }
            }
        }
        elseif ($Entry.transport -eq 'http') {
            # Windows 本机的 HTTP MCP（如 Burp 9876）
            $args = @($ProbeScript, '--http', $Entry.url)
            if ($Entry.token_file) { $args += @('--token-file', $Entry.token_file) }
            $r = Invoke-Capture -File 'python' -Arguments $args
            $j = Get-JsonFromText -Text $r.out
        }
        else {
            $args = @($ProbeScript, '--stdio', '--') + @($Entry.call)
            $r = Invoke-Capture -File 'python' -Arguments $args
            $j = Get-JsonFromText -Text $r.out
        }
        if (-not $j) {
            $row.detail = 'probe returned no JSON: ' + (($r.out -split "`r?`n" | Select-Object -Last 1))
            return [pscustomobject]$row
        }
        if ($j.ok) {
            if ($j.tools -ge [int]$Entry.min_tools) {
                $row.status = 'OK'; $row.detail = "$($j.tools) tools"
            }
            else {
                $row.detail = "$($j.tools) tools < min $($Entry.min_tools)"
            }
        }
        elseif ($j.state -eq 'down') {
            $row.status = 'DOWN'; $row.detail = ($j.error -replace "`r?`n", ' ').Substring(0, [Math]::Min(90, ($j.error -replace "`r?`n", ' ').Length))
        }
        else {
            $row.detail = $j.error
        }
        return [pscustomobject]$row
    }

    $row.detail = "unknown kind: $($Entry.kind)"
    return [pscustomobject]$row
}

# ------------------------------------------------------------------ main
if (-not (Test-Path -LiteralPath $Registry)) { throw "registry not found: $Registry" }
$reg = Get-Content -LiteralPath $Registry -Raw | ConvertFrom-Json

$rows = foreach ($e in $reg.entries) { Test-Entry -Entry $e }

$ok = @($rows | Where-Object status -eq 'OK').Count
$down = @($rows | Where-Object status -eq 'DOWN').Count
$fail = @($rows | Where-Object status -eq 'FAIL').Count

if ($Json) {
    [pscustomobject]@{
        registry = $Registry
        summary  = @{ ok = $ok; down = $down; fail = $fail }
        entries  = $rows
    } | ConvertTo-Json -Depth 5
}
else {
    Write-Host ''
    Write-Host '== CTF toolchain doctor ==' -ForegroundColor Cyan
    Write-Host "registry: $Registry"
    Write-Host ''
    foreach ($r in $rows) {
        $color = switch ($r.status) { 'OK' { 'Green' } 'DOWN' { 'Yellow' } 'FAIL' { 'Red' } default { 'Gray' } }
        Write-Host ('{0,-5} {1,-12} {2,-4} {3,-16} {4}' -f $r.status, $r.name, $r.kind, $r.side, $r.detail) -ForegroundColor $color
    }
    Write-Host ''
    Write-Host ("summary: {0} OK / {1} DOWN / {2} FAIL" -f $ok, $down, $fail)
    Write-Host ''
}

exit $fail
