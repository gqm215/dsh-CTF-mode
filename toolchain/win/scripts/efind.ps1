#requires -Version 7.0
<#
.SYNOPSIS
    用 Everything 索引做全盘文件定位，并过滤掉"索引里还在、磁盘上已删"的陈旧条目。

.DESCRIPTION
    Everything 的索引可能包含已删除/已移动的路径（实测 D:\RELab 整棵树都是幽灵条目），
    直接采信会把"这里有个 IDA"当成事实。所以这个 wrapper：
      1) 调 es.exe 拿 CSV（大小/修改时间/路径）
      2) 逐条 Test-Path 校验，默认丢弃不存在的
      3) 输出对象或 JSON，便于 Agent 直接消费

.EXAMPLE
    efind ida.exe
    efind -Path D:\CTF *.md -Max 10
    efind -Json p3-2-local
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory = $true)][string]$Query,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest,
    [int]$Max = 20,
    [string]$Path,
    [switch]$Json,
    [switch]$IncludeMissing,
    [string]$Es = 'D:\Tools\Everything\es.exe'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $Es)) { throw "es.exe not found: $Es" }

$esArgs = @('-csv', '-size', '-dm', '-n', "$Max")
if ($Path) { $esArgs += @('-path', $Path) }
$esArgs += @($Query)
if ($Rest) { $esArgs += $Rest }

$raw = & $Es @esArgs 2>&1
if ($LASTEXITCODE -ne 0) {
    $text = ($raw -join ' ')
    if ($text -match 'IPC window not found') {
        # Everything 没在跑：拉起它再试一次（隔夜/重启后常见）
        $exe = 'D:\Tools\Everything\Everything.exe'
        if (Test-Path -LiteralPath $exe) {
            Start-Process -FilePath $exe -WindowStyle Minimized -ErrorAction SilentlyContinue
            for ($i = 0; $i -lt 10; $i++) {
                Start-Sleep -Milliseconds 600
                $raw = & $Es @esArgs 2>&1
                if ($LASTEXITCODE -eq 0) { break }
            }
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "es.exe failed: $($raw -join ' ')" }
}

$rows = @($raw | Where-Object { $_ -and $_.Trim() }) | ConvertFrom-Csv -Header Size, Modified, FileName

$items = foreach ($r in $rows) {
    $exists = Test-Path -LiteralPath $r.FileName
    if (-not $exists -and -not $IncludeMissing) { continue }
    [pscustomobject]@{
        path     = $r.FileName
        name     = Split-Path -Leaf $r.FileName
        dir      = Split-Path -Parent $r.FileName
        size     = [int64]$r.Size
        modified = $r.Modified
        exists   = $exists
    }
}

$items = @($items)

if ($Json) {
    [pscustomobject]@{
        query   = $Query
        path    = $Path
        count   = $items.Count
        ghosts  = [int]($rows.Count - $items.Count)
        results = $items
    } | ConvertTo-Json -Depth 4
}
else {
    if (-not $items.Count) { Write-Host "no live result for: $Query" -ForegroundColor Yellow; return }
    $items | Format-Table -AutoSize @{ n = 'Size'; e = { '{0:N0}' -f $_.size } }, modified, path
    if ($rows.Count -gt $items.Count) {
        Write-Host ("({0} stale entries hidden; use -IncludeMissing to see them)" -f ($rows.Count - $items.Count)) -ForegroundColor DarkGray
    }
}

