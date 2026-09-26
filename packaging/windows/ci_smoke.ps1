#Requires -Version 5.1
<#
.SYNOPSIS
    Windows 免安装版冒烟测试：把刚打好的两个 exe 各起一次，确认真能监听并出页面。

.DESCRIPTION
    build.ps1 只保证「打包没报错」；PyInstaller 最常见的坑恰恰是**打包成功但一跑就
    崩**（漏了 hiddenimport、漏了数据文件）。这个脚本在 CI 里紧跟 build.ps1 跑，
    把这类问题拦在发布之前：

      1. 制卡端  → GET / 应 200，且能取到 ES Module 入口 assets/js/app.js 与 style.css
      2. 扫描端  → GET /api/health 应 200，且 GET / 能拿到首页
      3. 扫描端  → 数据目录里应出现 asb.db（证明 --data 生效、库能建起来）
      4. 顺带看一眼扫描端日志里 CNN 到底加载上没有（权重在包里，torch 装没装上
         只有日志知道）

    刻意的实现选择：**不用 Start-Process**，改用 System.Diagnostics.Process。
    原因是 Start-Process 会去构造一份大小写不敏感的环境变量字典，当父进程里
    同时存在 `Path` 和 `PATH`（某些 shell 会这样）时它会直接抛
    「字典中的关键字:"Path"所添加的关键字:"PATH"」而不是去启动进程。
    改成直接 Process.Start + 命令行参数就完全没有这个问题。

.EXAMPLE
    pwsh -File packaging/windows/ci_smoke.ps1
#>
[CmdletBinding()]
param(
    [int] $CardPort = 18899,
    [int] $ScanPort = 18881,
    [int] $WaitSeconds = 60
)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Here    = $PSScriptRoot
$Release = Join-Path $Here 'dist\release'
$DirCard = '答题卡制作器-Windows-x64'
$DirScan = '答题卡扫描服务-Windows-x64'

$Stamp = [guid]::NewGuid().ToString('N').Substring(0, 8)
$Tmp   = Join-Path ([System.IO.Path]::GetTempPath()) "asb-ci-smoke-$Stamp"
$Data  = Join-Path $Tmp 'data'
New-Item -ItemType Directory -Force -Path $Tmp, $Data | Out-Null

$script:Procs = @()

function Quote-Arg([string] $a) {
    if ($null -eq $a -or $a -eq '') { return '""' }
    if ($a -notmatch '[\s"]') { return $a }
    return '"' + (($a -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
}

function Start-Target([string] $Exe, [string] $Name, [string[]] $ArgList) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = (($ArgList | ForEach-Object { Quote-Arg $_ }) -join ' ')
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true

    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $psi
    [void]$p.Start()

    $t = [pscustomobject]@{
        P = $p
        Name = $Name
        Out = $p.StandardOutput.ReadToEndAsync()
        Err = $p.StandardError.ReadToEndAsync()
    }
    $script:Procs += $t
    return $t
}

function Stop-One($t) {
    try { if (-not $t.P.HasExited) { $t.P.Kill() } } catch { }
    try { [void]$t.P.WaitForExit(5000) } catch { }
}

function Get-Log($t) {
    # 必须先 Kill 再读 —— ReadToEndAsync 的 Result 会一直等到流关闭，进程不死就挂住
    Stop-One $t
    $o = ''; $e = ''
    try { if ($t.Out) { $o = $t.Out.Result } } catch { }
    try { if ($t.Err) { $e = $t.Err.Result } } catch { }
    return [pscustomobject]@{ Out = $o; Err = $e }
}

function Show-Log([string] $Name) {
    foreach ($t in $script:Procs | Where-Object { $_.Name -eq $Name }) {
        $l = Get-Log $t
        if ($l.Out) { Write-Host "----- $Name stdout -----"; Write-Host $l.Out.Trim() }
        if ($l.Err) { Write-Host "----- $Name stderr -----"; Write-Host $l.Err.Trim() }
    }
}

function Get-Text([string] $Url) {
    # 用 WebClient 而不是 Invoke-WebRequest：显式 UTF-8 解码（IWR 在拿不到
    # charset 时按 Latin-1 解，中文全花），并显式绕开代理。
    $wc = New-Object System.Net.WebClient
    $wc.Proxy = $null
    $wc.Encoding = [System.Text.Encoding]::UTF8
    $wc.Headers.Add('Cache-Control', 'no-store')
    try { return $wc.DownloadString($Url) } finally { $wc.Dispose() }
}

function Wait-Text([string] $Url, [int] $Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    $last = ''
    while ((Get-Date) -lt $deadline) {
        try { return Get-Text $Url } catch { $last = $_.Exception.Message }
        Start-Sleep -Milliseconds 800
    }
    throw "等 $Url 超时（$Seconds 秒）。最后错误：$last"
}

function Fail([string] $Msg) {
    Write-Host ''
    Write-Host "冒烟测试失败：$Msg" -ForegroundColor Red
    exit 1
}

try {
    # ---------------------------------------------------------- 制卡端
    $cardExe = Join-Path (Join-Path $Release $DirCard) '答题卡制作器.exe'
    if (-not (Test-Path -LiteralPath $cardExe)) { Fail "找不到制卡端 exe：$cardExe" }
    Write-Host "==> 启动制卡端：$cardExe（端口 $CardPort）"
    [void](Start-Target $cardExe 'card' @('--port', "$CardPort", '--no-browser'))

    $url = "http://127.0.0.1:$CardPort/"
    try { $html = Wait-Text $url $WaitSeconds }
    catch { Show-Log 'card'; Fail $_.Exception.Message }

    if ($html -notmatch 'assets/js/app\.js') {
        Show-Log 'card'
        Fail "制卡端首页异常：没找到 ES Module 入口 assets/js/app.js（长度 $($html.Length)）。"
    }
    # 单独再取一次静态资源，确认 assets/ 真的被打进包里了
    $js = Get-Text "http://127.0.0.1:$CardPort/assets/js/app.js"
    if ($js.Length -lt 1000) { Fail "制卡端 assets/js/app.js 内容异常（$($js.Length) 字节）。" }
    $css = Get-Text "http://127.0.0.1:$CardPort/assets/css/style.css"
    if ($css.Length -lt 1000) { Fail "制卡端 assets/css/style.css 内容异常（$($css.Length) 字节）。" }
    Write-Host "    制卡端 OK：index $($html.Length)B / app.js $($js.Length)B / style.css $($css.Length)B"

    # ---------------------------------------------------------- 扫描端
    $scanExe = Join-Path (Join-Path $Release $DirScan) '答题卡扫描服务.exe'
    if (-not (Test-Path -LiteralPath $scanExe)) { Fail "找不到扫描端 exe：$scanExe" }
    Write-Host "==> 启动扫描端：$scanExe（端口 $ScanPort）"
    $scanT = Start-Target $scanExe 'scan' @('--port', "$ScanPort", '--data', $Data, '--no-browser')

    $healthUrl = "http://127.0.0.1:$ScanPort/api/health"
    try { $health = Wait-Text $healthUrl $WaitSeconds }
    catch { Show-Log 'scan'; Fail $_.Exception.Message }
    if ($health -notmatch 'ok') {
        Show-Log 'scan'
        Fail "扫描端 /api/health 返回内容异常：$health"
    }
    $index = Get-Text "http://127.0.0.1:$ScanPort/"
    if ($index.Length -lt 1000) { Show-Log 'scan'; Fail "扫描端首页内容异常（$($index.Length) 字节）。" }

    $db = Join-Path $Data 'asb.db'
    if (-not (Test-Path -LiteralPath $db)) {
        Show-Log 'scan'
        Fail "扫描端没有在 --data 指定目录里建库：$db 不存在"
    }

    # 手写 CNN 到底装进去没有 —— 问服务，别猜。
    #
    # 这里原来 grep 启动日志里的「手写 CNN 已加载」，那是**永远不会触发**的：CNN 是懒加载的，
    # 第一次识别才尝试加载，而冒烟只打 /api/health 和 /，日志里根本不会有那一行 ——
    # 于是这个检查一直静默通过，等于没检查（584 MB 的包里到底有没有 torch，谁也不知道）。
    # 现在改成读 /api/health 的 `cnn` 字段：它静态回答「权重在不在 + torch 找不找得到」。
    $cnn = $null
    try { $cnn = ($health | ConvertFrom-Json).cnn } catch { }
    if ($null -eq $cnn) {
        Show-Log 'scan'
        Fail "扫描端 /api/health 没有返回 cnn 状态（旧版？）：$health"
    }
    # 权重文件在产物目录里就必须被认出来 —— 认不出说明打包时数据文件没落到 app/ 下。
    $weightsInPkg = @(Get-ChildItem -LiteralPath (Join-Path $Release $DirScan) -Recurse -File `
            -Filter 'hwletter_cnn.pt' -ErrorAction SilentlyContinue).Count -gt 0
    if ($weightsInPkg -and -not $cnn.weights) {
        Show-Log 'scan'
        Fail "产物里有 hwletter_cnn.pt，但服务说找不到权重（ASB_CNN_MODEL / DEFAULT_MODEL 路径不对）。"
    }
    if ($weightsInPkg -and -not $cnn.torch) {
        Show-Log 'scan'
        Fail "产物里有权重但没有 torch —— 打包时漏了 torch（构建机上没装？）。"
    }
    if ($cnn.ready) {
        Write-Host '    手写 CNN：已装入（权重 + torch 都在，第一次识别时加载）'
    } else {
        Write-Host '    手写 CNN：未装入（纯 OpenCV 模式，手写 A-D 精度会低一些）'
    }

    Write-Host "    扫描端 OK：health=$($health.Trim()) / index $($index.Length)B / asb.db $((Get-Item -LiteralPath $db).Length)B"

    Write-Host '冒烟测试全部通过。' -ForegroundColor Green
    exit 0
}
catch {
    Write-Host ''
    Write-Host "冒烟测试异常：$($_.Exception.Message)" -ForegroundColor Red
    Show-Log 'card'
    Show-Log 'scan'
    exit 1
}
finally {
    foreach ($t in $script:Procs) { Stop-One $t }
    Start-Sleep -Milliseconds 300
    if (Test-Path -LiteralPath $Tmp) { Remove-Item -LiteralPath $Tmp -Recurse -Force -ErrorAction SilentlyContinue }
}
