#requires -Version 7.0
<#
.SYNOPSIS
    Portable CTF toolchain bootstrap (Windows side).
    Copies the framework, detects installed tools into registry.json, generates bin shims,
    optionally adds the bin directory to the user PATH, then runs doctor.
#>
[CmdletBinding()]
param(
    [string]$Prefix = 'D:\CTF\Toolchain',
    [switch]$NoPath
)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
New-Item -ItemType Directory -Force -Path $Prefix, (Join-Path $Prefix 'scripts'), (Join-Path $Prefix 'bin'), (Join-Path $Prefix 'docs') | Out-Null
Get-ChildItem (Join-Path $Root 'win') -File | ForEach-Object { Copy-Item $_.FullName (Join-Path $Prefix $_.Name) -Force }
Get-ChildItem (Join-Path $Root 'win\scripts') -File | ForEach-Object { Copy-Item $_.FullName (Join-Path $Prefix 'scripts' $_.Name) -Force }
Get-ChildItem (Join-Path $Root 'win\docs') -File | ForEach-Object { Copy-Item $_.FullName (Join-Path $Prefix 'docs' $_.Name) -Force }
Copy-Item (Join-Path $Root 'portable\registry_init.py') (Join-Path $Prefix 'scripts\registry_init.py') -Force
Copy-Item (Join-Path $Root 'portable\gen_bin.ps1') (Join-Path $Prefix 'scripts\gen_bin.ps1') -Force
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue) }
if (-not $py) { throw 'python not found on PATH; install Python 3 first' }
& $py.Source (Join-Path $Prefix 'scripts\registry_init.py') --platform windows --registry (Join-Path $Prefix 'registry.json') --force
if ($LASTEXITCODE -ne 0) { throw "registry init failed: $LASTEXITCODE" }
pwsh -NoProfile -File (Join-Path $Prefix 'scripts\gen_bin.ps1') -Registry (Join-Path $Prefix 'registry.json') -Bin (Join-Path $Prefix 'bin')
if (-not $NoPath) {
    $bin = Join-Path $Prefix 'bin'
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($userPath -notlike "*$bin*") {
        [Environment]::SetEnvironmentVariable('Path', ($bin + ';' + $userPath), 'User')
        Write-Host "user PATH updated (new terminal required): $bin"
    }
}
& pwsh -NoProfile -File (Join-Path $Prefix 'doctor.ps1') -Registry (Join-Path $Prefix 'registry.json')
exit $LASTEXITCODE
