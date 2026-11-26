#requires -Version 7.0
<#
.SYNOPSIS
    三边一起体检：Windows 契约层 + Ubuntu-26.04 + kali-linux。

.DESCRIPTION
    Windows 侧跑 doctor.ps1；两个 WSL 发行版跑各自的
    ~/CTF_Lab/Toolchain/scripts/doctor.py --json。汇总 FAIL 数作为退出码。
#>
[CmdletBinding()]
param(
    [string]$WindowsDoctor = (Join-Path (Split-Path -Parent $PSScriptRoot) 'doctor.ps1'),
    [string]$WslDoctor = '/home/godfather/CTF_Lab/Toolchain/scripts/doctor.py'
)

$ErrorActionPreference = 'Stop'

$sides = @(
    @{ label = 'Ubuntu-26.04'; distro = 'Ubuntu-26.04' },
    @{ label = 'kali-linux';   distro = 'kali-linux' }
)

Write-Host ''
Write-Host '######## Windows 侧 ########' -ForegroundColor Cyan
& pwsh -NoProfile -File $WindowsDoctor
$totalFails = [int]$LASTEXITCODE
$rows = @()

foreach ($s in $sides) {
    Write-Host ("######## {0} 侧 ########" -f $s.label) -ForegroundColor Cyan
    $raw = & wsl -d $s.distro -u root -- python3 $WslDoctor --json 2>&1 | Out-String
    $parsed = $null
    try { $parsed = $raw | ConvertFrom-Json }
    catch {
        $start = $raw.IndexOf('{')
        if ($start -ge 0) { $parsed = $raw.Substring($start) | ConvertFrom-Json }
    }
    if (-not $parsed) {
        Write-Host ("{0}: doctor 输出无法解析" -f $s.label) -ForegroundColor Red
        $totalFails += 1
        continue
    }
    foreach ($e in $parsed.entries) {
        $color = switch ($e.status) { 'OK' { 'Green' } 'DOWN' { 'Yellow' } 'SKIP' { 'DarkGray' } default { 'Red' } }
        Write-Host ('{0,-5} {1,-18} {2,-7} {3}' -f $e.status, $e.name, $e.kind, $e.detail) -ForegroundColor $color
    }
    Write-Host ''
    Write-Host ("{0} summary: {1} OK / {2} DOWN / {3} FAIL / {4} SKIP" -f `
            $s.label, $parsed.summary.ok, $parsed.summary.down, $parsed.summary.fail, $parsed.summary.skip)
    Write-Host ''
    $totalFails += [int]$parsed.summary.fail
}

Write-Host ("TOTAL FAIL: {0}" -f $totalFails) -ForegroundColor $(if ($totalFails -eq 0) { 'Green' } else { 'Red' })
exit $totalFails
