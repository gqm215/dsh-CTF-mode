#requires -Version 7.0
<#
.SYNOPSIS
    MCP 冒烟测试：拉起 IDA / x64dbg，验证各自的 MCP 链路后关闭。

.DESCRIPTION
    IDA:  启动 -> 等 13337 -> stdio 代理 initialize+tools/list+check_connection -> 关闭
    x64dbg: 启动 -> 等 27042 -> node server initialize+tools/list -> 关闭

    两者都是"工具本身要开着才能用"的形态，所以这不是常驻服务探针，
    而是验收证据：证明接线正确、工具数正确、真实调用能通。
#>
[CmdletBinding()]
param(
    [string]$IdaExe = 'D:\Major_CompuTech_Suite\IDA Pro 9.3\ida.exe',
    [string]$IdaSamples = 'D:\网络空间安全 专业 课程体系\26秋 软件安全与逆向分析技术\实训\GZ_CTF\challenges\069_p3-2-local\attachment\p3-2-local',
    [string]$X64Exe = 'C:\Users\Geqim\AppData\Local\Microsoft\WinGet\Packages\x64dbg.x64dbg_Microsoft.Winget.Source_8wekyb3d8bbwe\release\x64\x64dbg.exe',
    [string]$X64Sample = 'C:\Windows\System32\whoami.exe',
    [string]$Probe = 'D:\CTF\Toolchain\scripts\mcp_probe.py'
)

$ErrorActionPreference = 'Stop'
function Wait-Port([int]$Port, [int]$Seconds = 60) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        Start-Sleep -Seconds 1
        if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { return $true }
    }
    return $false
}

$result = [ordered]@{ ida = 'skipped'; x64dbg = 'skipped' }

# ---------------- IDA ----------------
Write-Host '== IDA MCP ==' -ForegroundColor Cyan
if ((Test-Path $IdaExe) -and (Test-Path $IdaSamples)) {
    try {
        Start-Process -FilePath $IdaExe -ArgumentList '-A', "-S`"D:\CTF\Toolchain\scripts\ida_mcp_start.py`"", "`"$IdaSamples`"" -WindowStyle Minimized | Out-Null
        if (Wait-Port 13337 90) {
            $py = 'D:\Major_CompuTech_Suite\IDA Pro 9.3\python311\python.exe'
            $out = & $py $Probe --stdio --call check_connection -- $py -m ida_pro_mcp.server 2>&1 | Out-String
            $line = ($out -split "`r?`n" | Where-Object { $_.Trim().StartsWith('{') } | Select-Object -Last 1)
            $j = $line | ConvertFrom-Json
            if ($j.ok -and $j.call_ok) {
                Write-Host ("  OK  {0} tools | {1}" -f $j.tools, $j.call_result) -ForegroundColor Green
                $result.ida = "OK $($j.tools) tools"
            }
            else {
                Write-Host ("  FAIL probe: {0}" -f $line) -ForegroundColor Red
                $result.ida = 'FAIL'
            }
        }
        else { Write-Host '  FAIL: 13337 未监听' -ForegroundColor Red; $result.ida = 'FAIL' }
    }
    finally {
        Get-Process -Name ida -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 1
    }
}
else { Write-Host '  skip: 缺 IDA 或样例' -ForegroundColor DarkGray }

# ---------------- x64dbg ----------------
Write-Host '== x64dbg MCP ==' -ForegroundColor Cyan
if (Test-Path $X64Exe) {
    try {
        Start-Process -FilePath $X64Exe -ArgumentList "`"$X64Sample`"" -WindowStyle Minimized | Out-Null
        if (Wait-Port 27042 60) {
            $node = 'C:\Program Files\nodejs\node.exe'
            $entry = "$env:APPDATA\npm\node_modules\x64dbg-mcp-server\dist\index.js"
            $out = & python $Probe --stdio -- $node $entry 2>&1 | Out-String
            $line = ($out -split "`r?`n" | Where-Object { $_.Trim().StartsWith('{') } | Select-Object -Last 1)
            $j = $line | ConvertFrom-Json
            if ($j.ok) {
                Write-Host ("  OK  {0} tools" -f $j.tools) -ForegroundColor Green
                $result.x64dbg = "OK $($j.tools) tools"
            }
            else {
                Write-Host ("  FAIL probe: {0}" -f $line) -ForegroundColor Red
                $result.x64dbg = 'FAIL'
            }
        }
        else { Write-Host '  FAIL: 27042 未监听' -ForegroundColor Red; $result.x64dbg = 'FAIL' }
    }
    finally {
        Get-Process -Name x64dbg -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Seconds 1
    }
}
else { Write-Host '  skip: 缺 x64dbg' -ForegroundColor DarkGray }

Write-Host ''
Write-Host ("smoke: ida={0} | x64dbg={1}" -f $result.ida, $result.x64dbg)

