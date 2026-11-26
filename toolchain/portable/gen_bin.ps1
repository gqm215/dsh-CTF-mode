#requires -Version 7.0
<#
.SYNOPSIS
    Generate bin\*.cmd shims from registry.json (Windows side).
    Idempotent; only files carrying the managed-by marker are touched.
#>
[CmdletBinding()]
param(
    [string]$Registry = (Join-Path (Split-Path -Parent $PSScriptRoot) 'registry.json'),
    [string]$Bin = (Join-Path (Split-Path -Parent $PSScriptRoot) 'bin')
)
$ErrorActionPreference = 'Stop'
$marker = 'rem managed-by ctflab'
$reg = Get-Content -LiteralPath $Registry -Raw | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $Bin | Out-Null
# clean managed shims
Get-ChildItem $Bin -Filter *.cmd -File -ErrorAction SilentlyContinue | ForEach-Object {
    if (Select-String -LiteralPath $_.FullName -Pattern 'managed-by ctflab' -Quiet) { Remove-Item $_.FullName -Force }
}
$made = 0
foreach ($e in $reg.entries) {
    if ($e.kind -notin @('cli', 'gui')) { continue }
    $target = if ($e.entry) { $e.entry } else { $e.exec }
    if (-not $target) { continue }
    $name = $e.name
    $shim = Join-Path $Bin ($name + '.cmd')
    $line = '@echo off' + "`n" + $marker + "`n" + '"' + ($target -replace '/', '\') + '" %*' + "`n"
    Set-Content -LiteralPath $shim -Value $line -Encoding ascii
    $made++
}
Write-Host ("bin shims: {0} written to {1}" -f $made, $Bin)
