#requires -Version 7.0
<#
.SYNOPSIS
    接管手动下载的 GUI 安装包：自动识别 Burp / WinDbg，安装并登记。

.DESCRIPTION
    放到 D:\SecTools\GUI 的安装包会被本脚本识别：
      burp*.exe              -> 静默安装（NSIS /S）到 D:\SecTools\GUI\BurpSuiteCommunity
      *.msixbundle / *.msix  -> Add-AppxPackage 安装 WinDbg
      winsdk*.exe            -> 静默安装调试工具（OptionId.WindowsDesktopDebuggers）

    装完自动写 registry.json（kind=gui 或 mcp），并提示跑 doctor。
    没有匹配文件时只打印期望，不做任何事。

.EXAMPLE
    pwsh -File D:\CTF\Toolchain\scripts\install-gui-pack.ps1
#>
[CmdletBinding()]
param(
    [string]$Inbox = 'D:\SecTools\GUI',
    [string]$Registry = (Join-Path (Split-Path -Parent $PSScriptRoot) 'registry.json')
)

$ErrorActionPreference = 'Stop'
$reg = Get-Content -LiteralPath $Registry -Raw | ConvertFrom-Json

function Add-Entry($entry) {
    if ($reg.entries | Where-Object name -eq $entry.name) {
        Write-Host "  registry already has $($entry.name)" -ForegroundColor DarkGray
        return
    }
    $script:reg.entries = @($script:reg.entries) + $entry
    $script:reg | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Registry -Encoding utf8
    Write-Host "  registered: $($entry.name)" -ForegroundColor Green
}

$found = $false

# ---- Burp
$burp = Get-ChildItem -LiteralPath $Inbox -File -Filter 'burp*.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($burp) {
    $found = $true
    $target = Join-Path $Inbox 'BurpSuiteCommunity'
    Write-Host "Burp installer: $($burp.FullName)" -ForegroundColor Cyan
    Write-Host "  installing to $target ..."
    Start-Process -FilePath $burp.FullName -ArgumentList "/S", "/D=$target" -Wait
    $exe = Join-Path $target 'BurpSuiteCommunity.exe'
    if (Test-Path $exe) {
        Write-Host "  installed: $exe" -ForegroundColor Green
        Add-Entry ([pscustomobject]@{
            name = 'burp'; kind = 'gui'; side = 'win'; exec = ($exe -replace '\\', '/')
            category = @('web'); notes = 'Burp Community；MCP 走官方 BApp「MCP Server」扩展（需在 Burp 里装并开端口）。'
        })
    }
    else {
        Write-Host "  expected exe not found; check install dir" -ForegroundColor Yellow
    }
}

# ---- WinDbg
$msix = Get-ChildItem -LiteralPath $Inbox -File -Include '*.msixbundle', '*.msix' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($msix) {
    $found = $true
    Write-Host "WinDbg package: $($msix.FullName)" -ForegroundColor Cyan
    Add-AppxPackage -Path $msix.FullName
    Write-Host "  installed (appx)" -ForegroundColor Green
    Add-Entry ([pscustomobject]@{
        name = 'windbg'; kind = 'mcp'; transport = 'stdio'; side = 'win'; user = 'Geqim'
        call = @('python', '-m', 'mcp_windbg')
        min_tools = 3
        category = @('reverse'); notes = 'WinDbg/cdb + mcp-windbg；首次使用需设置 dump 路径或附加调试目标。'
    })
}

# ---- Windows SDK debuggers
$sdk = Get-ChildItem -LiteralPath $Inbox -File -Filter 'winsdk*.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($sdk) {
    $found = $true
    Write-Host "SDK installer: $($sdk.FullName)" -ForegroundColor Cyan
    Start-Process -FilePath $sdk.FullName -ArgumentList '/features', 'OptionId.WindowsDesktopDebuggers', '/q', '/norestart' -Wait
    $cdb = 'C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\cdb.exe'
    if (Test-Path $cdb) {
        Write-Host "  cdb installed: $cdb" -ForegroundColor Green
        Add-Entry ([pscustomobject]@{
            name = 'cdb'; kind = 'cli'; side = 'win'; exec = ($cdb -replace '\\', '/')
            category = @('reverse'); notes = 'Windows SDK 调试器命令行；mcp-windbg 依赖它。'
        })
    }
}

if (-not $found) {
    Write-Host "D:\SecTools\GUI 里没有可识别的安装包。期望文件名：" -ForegroundColor Yellow
    Write-Host "  burp*.exe | *.msixbundle | winsdk*.exe"
}

Write-Host ''
Write-Host '下一步：pwsh -File D:\CTF\Toolchain\gen_tools.ps1; pwsh -File D:\CTF\Toolchain\doctor.ps1'
