#requires -Version 7.0
<#
.SYNOPSIS
    已安装工具清点：枚举"装机记录"，而不是猜路径。

.DESCRIPTION
    历史教训：靠固定路径清单找工具，会漏掉 WinGet / Chocolatey / npm 装在非标准位置的东西
    （x64dbg 就因此在盘点里被误判为"没装"）。这里改成从安装记录反向枚举：
      - winget list（权威）
      - 开始菜单快捷方式（用户 + 全局）
      - 包管理器目录（WinGet Packages / Chocolatey / Scoop / npm / dotnet tools）
      - 常见安装根（Program Files、LOCALAPPDATA\Programs、D:\Tools、D:\Major_CompuTech_Suite、D:\SecTools）
    再拿工具目录去匹配。注意：只覆盖 Windows 侧，WSL 里的工具要另外盘点。

.EXAMPLE
    pwsh -File D:\CTF\Toolchain\discover.ps1
    pwsh -File D:\CTF\Toolchain\discover.ps1 -Json
#>
[CmdletBinding()]
param(
    [switch]$Json,
    [string]$OutFile = (Join-Path $PSScriptRoot 'state\inventory.json')
)

$ErrorActionPreference = 'SilentlyContinue'

$catalog = @(
    @{ name = 'IDA Pro';        pattern = 'IDA Pro|IDA Free|Hex-Rays' }
    @{ name = 'x64dbg';         pattern = 'x64dbg|x32dbg' }
    @{ name = 'Ghidra';         pattern = 'Ghidra' }
    @{ name = 'radare2/rizin';  pattern = 'radare2|rizin|Cutter' }
    @{ name = 'Wireshark';      pattern = 'Wireshark' }
    @{ name = 'Burp Suite';     pattern = 'Burp' }
    @{ name = 'dnSpy';          pattern = 'dnSpy' }
    @{ name = 'de4dot';         pattern = 'de4dot' }
    @{ name = 'Detect It Easy'; pattern = 'Detect It Easy' }
    @{ name = 'PE-bear';        pattern = 'PE-bear|PEbear' }
    @{ name = 'HxD';            pattern = 'HxD' }
    @{ name = '010 Editor';     pattern = '010 Editor' }
    @{ name = 'CFF Explorer';   pattern = 'CFF ?Explorer' }
    @{ name = 'WinDbg';         pattern = 'WinDbg|Debugging Tools for Windows' }
    @{ name = 'Sysinternals';   pattern = 'Sysinternals|Procmon|Process Monitor|Autoruns' }
    @{ name = 'Frida';          pattern = 'Frida' }
    @{ name = 'jadx';           pattern = 'jadx' }
    @{ name = 'apktool';        pattern = 'apktool' }
    @{ name = 'Android Studio'; pattern = 'Android Studio' }
    @{ name = 'VMware';         pattern = 'VMware' }
    @{ name = 'adb';            pattern = 'platform-tools|Android SDK Platform' }
    @{ name = 'nmap';           pattern = 'nmap' }
    @{ name = 'Python';         pattern = 'Python 3\.\d+' }
    @{ name = 'Java';           pattern = 'Java|JDK|JBR' }
    @{ name = 'Node.js';        pattern = 'Node\.js' }
    @{ name = 'Docker';         pattern = 'Docker' }
    @{ name = 'Tailscale';      pattern = 'Tailscale' }
)

$entries = New-Object System.Collections.Generic.List[object]
function Add-Entry([string]$source, [string]$text) {
    if ($text) { $entries.Add([pscustomobject]@{ source = $source; text = $text.Trim() }) }
}

# ---------------------------------------------------------------- 采集
$winget = winget list --disable-interactivity 2>$null | Out-String
foreach ($line in ($winget -split "`r?`n")) {
    if ($line -match '^\S' -and $line -notmatch '^Name\s+Id') {
        Add-Entry 'winget' (($line -split '\s{2,}')[0])
    }
}

foreach ($root in @("$env:APPDATA\Microsoft\Windows\Start Menu\Programs",
                    'C:\ProgramData\Microsoft\Windows\Start Menu\Programs')) {
    Get-ChildItem -LiteralPath $root -Recurse -Filter *.lnk -ErrorAction SilentlyContinue |
        ForEach-Object { Add-Entry 'startmenu' $_.BaseName }
}

$pkgs = @(
    @{ src = 'winget-pkg';  path = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" }
    @{ src = 'chocolatey';  path = 'C:\ProgramData\chocolatey\lib' }
    @{ src = 'scoop';       path = "$env:USERPROFILE\scoop\apps" }
    @{ src = 'npm';         path = "$env:APPDATA\npm" }
    @{ src = 'dotnet-tool'; path = "$env:USERPROFILE\.dotnet\tools" }
)
foreach ($d in $pkgs) {
    Get-ChildItem -LiteralPath $d.path -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Add-Entry $d.src $_.Name }
}

foreach ($root in @('C:\Program Files', 'C:\Program Files (x86)', "$env:LOCALAPPDATA\Programs",
                    'D:\Tools', 'D:\Major_CompuTech_Suite', 'D:\SecTools')) {
    Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Add-Entry 'programs' "$root\$($_.Name)" }
}

# ---------------------------------------------------------------- 匹配
$rows = foreach ($tool in $catalog) {
    $hits = @($entries | Where-Object { $_.text -match $tool.pattern } | Select-Object -First 3)
    [pscustomobject]@{
        tool   = $tool.name
        status = if ($hits.Count -gt 0) { 'FOUND' } else { 'MISSING' }
        hits   = @($hits | ForEach-Object { "$($_.source):$($_.text)" })
    }
}

$counts = @{
    found   = @($rows | Where-Object status -eq 'FOUND').Count
    missing = @($rows | Where-Object status -eq 'MISSING').Count
}

New-Item -ItemType Directory -Force -Path (Split-Path $OutFile) | Out-Null
[pscustomobject]@{
    generated = (Get-Date -Format 's')
    sources   = $entries.Count
    counts    = $counts
    tools     = $rows
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutFile -Encoding utf8

if ($Json) {
    [pscustomobject]@{ counts = $counts; tools = $rows } | ConvertTo-Json -Depth 6
}
else {
    Write-Host ''
    Write-Host '== 已安装工具清点（按安装记录枚举，仅 Windows 侧）==' -ForegroundColor Cyan
    $sorted = $rows | Sort-Object -Property @{ Expression = { if ($_.status -eq 'FOUND') { 0 } else { 1 } } }, tool
    foreach ($r in $sorted) {
        $color = if ($r.status -eq 'FOUND') { 'Green' } else { 'DarkGray' }
        Write-Host ('{0,-14} {1,-8} {2}' -f $r.tool, $r.status, ($r.hits -join ' | ')) -ForegroundColor $color
    }
    Write-Host ''
    Write-Host ("FOUND {0} / MISSING {1}   (sources {2})" -f $counts.found, $counts.missing, $entries.Count)
    Write-Host ''
}
