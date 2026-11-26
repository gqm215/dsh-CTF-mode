#requires -Version 7.0
<#
.SYNOPSIS
    由 registry.json 生成 TOOLS.md（给人和 Agent 看的工具说明书）。

.DESCRIPTION
    只读 registry.json，不改任何工具状态。改完注册表重跑即可。
#>
[CmdletBinding()]
param(
    [string]$Registry = (Join-Path $PSScriptRoot 'registry.json'),
    [string]$WslRegistry = (Join-Path $PSScriptRoot 'scripts\wsl\registry.json'),
    [string]$KaliRegistry = (Join-Path $PSScriptRoot 'scripts\kali\registry.json'),
    [string]$OutFile = (Join-Path $PSScriptRoot 'TOOLS.md')
)

$ErrorActionPreference = 'Stop'
$reg = Get-Content -LiteralPath $Registry -Raw | ConvertFrom-Json
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm'

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add('# TOOLS — 本机 CTF 工具链')
$lines.Add('')
$lines.Add("> 自动生成（$stamp），**不要手改**；改 ``registry.json`` 后跑 ``gen_tools.ps1``。")
$lines.Add('> 调用纪律：只走 PATH 里的入口或本文档列出的命令，**禁止猜绝对路径**；路径变了就改注册表。')
$lines.Add('')

$mcp = @($reg.entries | Where-Object kind -eq 'mcp')
if ($mcp.Count) {
    $lines.Add('## MCP 服务')
    $lines.Add('')
    $lines.Add('| 名称 | 位置 | 入口 | 说明 |')
    $lines.Add('|---|---|---|---|')
    foreach ($e in $mcp) {
        $where = if ($e.transport -eq 'http') { "``$($e.url)``" } else { '``' + (($e.call) -join ' ') + '``' }
        $lines.Add("| ``$($e.name)`` | $($e.side) | $where | $($e.notes) |")
    }
    $lines.Add('')
    $lines.Add('> WSL 内的服务只绑 127.0.0.1，**Windows 侧直连不到**；从 Windows 调用要经 `wsl -d Ubuntu-26.04` 或 stdio 桥。')
    $lines.Add('')
}

$cli = @($reg.entries | Where-Object kind -eq 'cli')
if ($cli.Count) {
    $lines.Add('## CLI')
    $lines.Add('')
    $lines.Add('| 名称 | 调用入口 | 实体 | 方向 | 说明 |')
    $lines.Add('|---|---|---|---|---|')
    foreach ($e in $cli) {
        $cat = if ($e.category) { $e.category -join '/' } else { '' }
        $entry = if ($e.entry) { $e.entry } else { $e.exec }
        $entity = if ($e.entry) { $e.exec } else { '-' }
        $lines.Add("| ``$($e.name)`` | ``$entry`` | ``$entity`` | $cat | $($e.notes) |")
    }
    $lines.Add('')
}

$gui = @($reg.entries | Where-Object kind -eq 'gui')
if ($gui.Count) {
    $lines.Add('## GUI（只启动，不纳入自动调用）')
    $lines.Add('')
    $lines.Add('| 名称 | 实体 | 说明 |')
    $lines.Add('|---|---|---|')
    foreach ($e in $gui) {
        $lines.Add("| ``$($e.name)`` | ``$($e.exec)`` | $($e.notes) |")
    }
    $lines.Add('')
}

if (Test-Path -LiteralPath $WslRegistry) {
    $wsl = Get-Content -LiteralPath $WslRegistry -Raw | ConvertFrom-Json
    $lines.Add('## WSL 侧（Ubuntu-26.04，`~/CTF_Lab/Toolchain/scripts/doctor.py` 体检）')
    $lines.Add('')
    $lines.Add('| 名称 | kind | 探针 / 说明 |')
    $lines.Add('|---|---|---|')
    foreach ($e in $wsl.entries) {
        $how = switch ($e.kind) {
            'cmd'   { "``$($e.cmd)``" }
            'path'  { "``$($e.path)``" }
            'probe' { '``' + ($e.probe -replace '\|', '\|') + '``' }
            'http'  { "``$($e.url)``" }
            default { $e.kind }
        }
        $lines.Add("| ``$($e.name)`` | $($e.kind) | $how |")
    }
    $lines.Add('')
}

if (Test-Path -LiteralPath $KaliRegistry) {
    $kali = Get-Content -LiteralPath $KaliRegistry -Raw | ConvertFrom-Json
    $lines.Add('## kali 侧（WSL kali-linux，同一套 doctor.py）')
    $lines.Add('')
    $lines.Add('| 名称 | kind | 探针 / 说明 |')
    $lines.Add('|---|---|---|')
    foreach ($e in $kali.entries) {
        $how = switch ($e.kind) {
            'cmd'   { "``$($e.cmd)``" }
            'path'  { "``$($e.path)``" }
            'probe' { '``' + ($e.probe -replace '\|', '\|') + '``' }
            'http'  { "``$($e.url)``" }
            default { $e.kind }
        }
        $lines.Add("| ``$($e.name)`` | $($e.kind) | $how |")
    }
    $lines.Add('')
}

$lines.Add('## 入口')
$lines.Add('')
$lines.Add('- Windows：`D:\CTF\Toolchain\bin` 进 PATH，`ctf-doctor` 体检。')
$lines.Add('- WSL：`~/CTF_Lab/Toolchain/bin`，`python3 ~/CTF_Lab/Toolchain/scripts/doctor.py` 体检。')
$lines.Add('- 两侧一起：`pwsh -File D:\CTF\Toolchain\scripts\doctor-all.ps1`。')
$lines.Add('')

Set-Content -LiteralPath $OutFile -Value $lines -Encoding utf8
Write-Host "wrote $OutFile ($($reg.entries.Count) entries + WSL)"
