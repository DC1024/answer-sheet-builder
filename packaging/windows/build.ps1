#Requires -Version 5.1
<#
.SYNOPSIS
    打包「答题卡制作器 / 答题卡扫描识别服务」的 Windows 免安装版（PyInstaller）。

.DESCRIPTION
    产出两个 zip，可直接作为 GitHub Release 的资产：
        packaging/windows/dist/release/*-cardmaker-windows-x64.zip
        packaging/windows/dist/release/*-scanner-windows-x64.zip

    本脚本必须以 **UTF-8 with BOM** 保存：Windows PowerShell 5.1 会把无 BOM 的
    UTF-8 脚本按 ANSI(936) 解码，中文全成乱码并连带报出一堆「字符串缺少终止符」
    的假语法错误。PS7 认 BOM，所以同一份脚本在本地 5.1 和 CI 的 pwsh 下都能跑。

.EXAMPLE
    pwsh -File packaging/windows/build.ps1 -Version v1.0.3

.EXAMPLE
    # 本地快速验证：不打 zip、不带 CNN
    powershell -File packaging/windows/build.ps1 -NoCnn -SkipZip
#>
[CmdletBinding()]
param(
    [string] $Version = 'dev',
    [string] $Python = '',
    [switch] $NoCnn,
    [switch] $SkipZip
)

# 注意：这里**不能**设 'Stop'。PowerShell 5.1 下 `$ErrorActionPreference='Stop'`
# 会把「原生程序往 stderr 写一行」也当成终止错误（NativeCommandError）——而
# PyInstaller / pip 恰恰把 INFO/WARN 日志全写在 stderr，脚本会在第一行日志处
# 直接炸掉。所以改成 'Continue'，失败一律靠显式检查 $LASTEXITCODE 兜住。
$ErrorActionPreference = 'Continue'

# 让控制台按 UTF-8 输出，CI 日志里中文才不是乱码
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Here       = $PSScriptRoot
$Root       = (Resolve-Path (Join-Path $Here '..\..')).Path
$BuildRoot  = Join-Path $Here 'build'
$DistRoot   = Join-Path $Here 'dist'
# PyInstaller 的 --workpath 用**每次构建都不同**的新目录。
#   原因：它开工会先 rmtree 掉已有 workpath，而这一步在某些受管环境里会被拦（一次删几千个
#   文件），拦下来就表现为「制卡端打包失败（exit 1）」这种跟打包本身毫无关系的报错。
#   给个新目录就完全不需要删了 —— 顺带也把「上一次的分析残留被这次收进去」这类
#   看着毫无道理的坑一起消灭（我们之前就踩过一个）。
$WorkRoot   = Join-Path $BuildRoot ('work-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$ReleaseDir = Join-Path $DistRoot 'release'
# 组装用的暂存目录同理，每次换新的（见上），收尾清理一律软失败（-Soft）。
$StageRoot  = Join-Path $DistRoot ('stage-' + [guid]::NewGuid().ToString('N').Substring(0, 8))

$DirCard = '答题卡制作器-Windows-x64'
$DirScan = '答题卡扫描服务-Windows-x64'
$CardExeName = '答题卡制作器'
$ScanExeName = '答题卡扫描服务'

function Write-Step([string] $Text) {
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Remove-Safe([string] $Path, [switch] $Soft) {
    # 只允许删 dist / build 底下的东西，防手滑。
    #
    # $Soft 用于**构建收尾**的清理（stage / release 这类临时目录）：那里删不掉只是一点
    # 磁盘残留，**绝不该让一次已经成功的构建变成失败**。构建前清 dist 则必须用硬模式，
    # 因为删不干净会被 PyInstaller 把上一次的 _internal 一起收进去（表现为「少了一个包」
    # 这种看着毫无道理的报错）。
    if (-not $Path) { return }
    $full = [System.IO.Path]::GetFullPath($Path)
    $guard = [System.IO.Path]::GetFullPath($DistRoot)
    $guard2 = [System.IO.Path]::GetFullPath($BuildRoot)
    if (-not ($full.StartsWith($guard, 'OrdinalIgnoreCase') -or
              $full.StartsWith($guard2, 'OrdinalIgnoreCase'))) {
        throw "拒绝删除 $full —— 它不在 dist/ 或 build/ 下面。"
    }
    if (-not (Test-Path -LiteralPath $full)) { return }

    try {
        Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
    } catch {
        $why = $_.Exception.Message
        # 受管环境（比如给 Remove-Item 套了批量删除确认的壳）会拒绝一次删几百个文件，
        # 而它抛的是一坨 NativeCommandError，看不出真正原因，所以这里自己包一层。
        if ($Soft) {
            Write-Warning "临时目录没清干净，不影响产物，可以手动删：$full`n  原因：$why"
            return
        }
        throw ("清不掉旧目录：$full`n" +
               "  原因：$why`n" +
               "  多半是这个 shell 给 Remove-Item 套了批量删除确认/拦截的包装。" +
               "手动删掉它（或整个 $DistRoot）再重跑即可 —— 那是构建产物，删了没损失。`n" +
               "  注意 dist/ 里如果有上一次的 _internal，**必须**删掉再构建，否则会打进旧文件。")
    }
}

function Write-Utf8Bom([string] $Path, [string] $Text) {
    # 用 .NET 写：跨 PS 5.1 / 7 行为一致，且明确带 BOM，记事本打开中文不乱。
    # 顺手把行尾统一成 CRLF（脚本本身多半是 LF 检出的），老工具最省事。
    $body = (($Text -replace "`r`n", "`n") -replace "`n", "`r`n").TrimStart()
    $enc = New-Object System.Text.UTF8Encoding($true)
    [System.IO.File]::WriteAllText($Path, $body, $enc)
}

function Invoke-Native([string] $Exe, [string[]] $ArgList) {
    # 跑原生程序并只返回退出码。刻意把 $ErrorActionPreference 降到 Continue：
    # 否则 PS 5.1 会把程序写进 stderr 的任何一行升级成终止错误（见文件头注释）。
    #
    # 顺手把 stderr 用 2>&1 合并后再自己分流输出：PS 5.1 会把原生程序的每一条
    # stderr 包装成 ErrorRecord 并按「错误」渲染（红色 + 一大坨 CategoryInfo 噪音），
    # PyInstaller / pip 的 INFO/WARN 日志全走 stderr，不处理的话日志会非常吓人。
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $code = 1
    try {
        & $Exe @ArgList 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                [Console]::Error.WriteLine($_.ToString())
            } else {
                Write-Host $_
            }
        }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prev
    }
    return $code
}

# ---------------------------------------------------------------- 找解释器

function Resolve-Python([string] $Hint, [string] $RepoRoot) {
    if ($Hint) {
        if (Test-Path -LiteralPath $Hint) { return (Resolve-Path -LiteralPath $Hint).Path }
        throw "找不到指定的 Python：$Hint"
    }
    $cands = @(
        (Join-Path $RepoRoot 'scanner\.venv\Scripts\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
    )
    foreach ($c in $cands) {
        if ($c -and (Test-Path -LiteralPath $c)) { return (Resolve-Path -LiteralPath $c).Path }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw '找不到 Python，请用 -Python 指定解释器路径。'
}

$py = Resolve-Python $Python $Root
Write-Host "Python : $py"
Write-Host "仓库根 : $Root"

# ---------------------------------------------------------------- 依赖

$pyiVer = ''
try { $pyiVer = (& $py -m PyInstaller --version 2>$null | Select-Object -First 1) } catch { }
if (-not $pyiVer) {
    Write-Host '未检测到 PyInstaller，正在安装…'
    $code = Invoke-Native $py @('-m', 'pip', 'install', '--upgrade', 'pyinstaller')
    if ($code -ne 0) { throw "PyInstaller 安装失败（exit $code）" }
    $pyiVer = (& $py -m PyInstaller --version | Select-Object -First 1)
}
Write-Host "PyInstaller : $pyiVer"

$torchVer = ''
try { $torchVer = (& $py -c "import torch;print(torch.__version__)" 2>$null | Select-Object -First 1) } catch { }
$hasTorch = [bool]($torchVer)
if ($hasTorch) { Write-Host "torch : $torchVer" } else { Write-Host 'torch : （未安装）' }

# ---------------------------------------------------------------- 构建

Write-Step "[1/2] 打包制卡端（纯静态站点 → 单文件 exe）"
Remove-Safe (Join-Path $DistRoot 'cardmaker')   # 先自己清干净，别依赖 PyInstaller 的 --noconfirm
$env:ASB_WIN_EXE_NAME = $CardExeName
$code = Invoke-Native $py @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN',
    '--distpath', (Join-Path $DistRoot 'cardmaker'),
    '--workpath', (Join-Path $WorkRoot 'cardmaker'),
    (Join-Path $Here 'cardmaker.spec')
)
if ($code -ne 0) { throw "制卡端打包失败（exit $code）" }
$env:ASB_WIN_EXE_NAME = ''

$withCnn = -not $NoCnn
if ($withCnn -and -not $hasTorch) {
    Write-Warning '构建环境里没有 torch —— 扫描端不带手写 CNN，识别自动退回纯 OpenCV。'
    $withCnn = $false
}
Write-Step "[2/2] 打包扫描端（Flask + OpenCV$(if ($withCnn) { ' + 手写 CNN' }) → onedir）"
Remove-Safe (Join-Path $DistRoot 'scanner')
if ($withCnn) { $env:ASB_WIN_WITH_CNN = '1' } else { $env:ASB_WIN_WITH_CNN = '0' }
$env:ASB_WIN_EXE_NAME = $ScanExeName
$code = Invoke-Native $py @(
    '-m', 'PyInstaller', '--noconfirm', '--clean', '--log-level', 'WARN',
    '--distpath', (Join-Path $DistRoot 'scanner'),
    '--workpath', (Join-Path $WorkRoot 'scanner'),
    (Join-Path $Here 'scanner.spec')
)
if ($code -ne 0) { throw "扫描端打包失败（exit $code）" }
$env:ASB_WIN_EXE_NAME = ''

# ---------------------------------------------------------------- 组装

Write-Step '组装免安装目录'
# 这次删除必须是**硬失败**：release 里的残留会以「合并」的方式留在产物里
# （比如先带 CNN 构建、再去掉 CNN 重建，包里会仍然带着上一次的 torch DLL，
# 体积对不上、行为也不可预期），不能像收尾清理那样将就。
Remove-Safe $ReleaseDir
New-Item -ItemType Directory -Force -Path $ReleaseDir, $StageRoot | Out-Null

$cardSrc = Join-Path $DistRoot 'cardmaker'
# onedir 的产物目录名 = EXE 名（COLLECT 的 name），所以直接照着找
$scanSrc = Join-Path $DistRoot ('scanner\' + $ScanExeName)
if (-not (Test-Path -LiteralPath (Join-Path $scanSrc ($ScanExeName + '.exe')))) {
    $scanSrc = Join-Path $DistRoot 'scanner\ASB-Scanner'
}
if (-not (Test-Path -LiteralPath $scanSrc)) { throw "找不到扫描端产物目录：$scanSrc" }

$cardDir = Join-Path $ReleaseDir $DirCard
$scanDir = Join-Path $ReleaseDir $DirScan
New-Item -ItemType Directory -Force -Path $cardDir, $scanDir | Out-Null

Copy-Item -Path (Join-Path $cardSrc '*') -Destination $cardDir -Recurse -Force
Copy-Item -Path (Join-Path $scanSrc '*') -Destination $scanDir -Recurse -Force

# $ErrorActionPreference 是 Continue，Copy-Item 失败不会自己炸 —— 显式验一下
foreach ($need in @(
        (Join-Path $cardDir ($CardExeName + '.exe')),
        (Join-Path $scanDir ($ScanExeName + '.exe')))) {
    if (-not (Test-Path -LiteralPath $need)) { throw "组装后缺文件：$need" }
}

# ---- 使用说明（UTF-8 BOM，记事本双击不乱码）

$cardReadme = @"
答题卡制作器 · Windows 免安装版（$Version）
================================================

一、怎么用
  双击本目录里的「答题卡制作器.exe」。
  程序会在本机起一个很小的网页服务，并自动打开浏览器；用蓝色的那个程序窗口
  按 Ctrl+C 就能退出，直接关掉窗口也可以。

  为什么不是一个 html 文件？
  制卡端的脚本是 ES Module，浏览器不允许在 file:// 下加载模块 —— 双击 html
  只会得到一片白屏。所以免安装版自带了一个只监听本机的本地服务。

二、数据存在哪
  点界面上的「保存」，内容存在浏览器自己的本地存储里（换浏览器或换端口就看不到）。
  要备份、换机器，用「⬇ 导出 JSON」，在新机器上「⬆ 导入 JSON」即可。

三、常见问题
  · 浏览器没自动打开：手动访问窗口里显示的地址（默认形如 http://127.0.0.1:端口/）。
  · 端口被占用：在窗口里加参数指定一个别的端口
        答题卡制作器.exe --port 8899
    （也认环境变量：set ASB_PORT=8899）
  · Windows 提示「已保护你的电脑」：这是未做数字签名的免安装程序的常规提示，
    点「更多信息」→「仍要运行」。
  · 打印 / 导出 PDF：请用浏览器打印对话框，纸张选 A3 或 A4、缩放 100%、
    边距「无」，否则定位点会和内容错位。
  · 其它参数：答题卡制作器.exe --help

四、和扫描端配合
  点「🎯 阅卷模板」导出的 JSON，就是扫描端要上传的模板文件。
"@
Write-Utf8Bom (Join-Path $cardDir '使用说明.txt') $cardReadme

if ($withCnn) {
    $cnnText = @"
  本版本【已包含】手写 A-D 的 CNN 增强模型：手写作答框用 CNN 一选 + OpenCV
  交叉验证，两者不一致或 CNN 置信不足会标为「存疑」进复核队列（绝不硬猜）。
  实测真实手写整卷净准确率 94.3%（仅 OpenCV 时为 75.5%）。
  想省内存可以关掉： set ASB_NO_CNN=1
"@
} else {
    $cnnText = @"
  本版本【未包含】手写 A-D 的 CNN 增强模型（构建环境无 PyTorch）：手写作答框
  走纯 OpenCV 特征分类，实测真实手写净准确率 75.5%。识别结果照样会在置信不足
  或双字母时标为「存疑」进复核队列 —— 宁可让老师看一眼，也不替你硬猜。
"@
}

$scanReadme = @"
答题卡扫描识别服务 · Windows 免安装版（$Version）
================================================

一、怎么用
  1. 双击本目录里的「答题卡扫描服务.exe」。
     程序会在本机起服务并自动打开浏览器（只在这个窗口关掉时才会停止）。
  2. 首次运行按网页提示创建管理员账号。
  3. 依次：上传「阅卷模板」（制卡端「🎯 阅卷模板」导出的 JSON）→ 上传标准答案
     → 上传扫描图（支持 zip 压缩包 / 整个文件夹 / 一堆散图）→ 识别 → 复核 → 导出成绩。
  4. 用完在窗口里按 Ctrl+C 退出，或直接关掉窗口。

二、数据存在哪
  %LOCALAPPDATA%\asb-scanner\data\
      asb.db        考试 / 名单 / 学生 / 标准答案 / 评分规则
      <随机ID>.png   识别时生成的校对图
  备份就是拷这个目录；删掉等于恢复出厂设置（不可逆）。

三、让同网段其他电脑也能访问
  默认只监听 127.0.0.1（仅本机）。需要给学生端或另一台电脑看时：
      答题卡扫描服务.exe --host 0.0.0.0
  然后别人访问 http://<你这台机器的内网IP>:8081/ 。
  这种情况下请务必先改掉默认口令。

四、手写字母识别
$cnnText

五、常见问题
  · Windows 提示「已保护你的电脑」：免安装程序没有数字签名，点「更多信息」→
    「仍要运行」即可。
  · 端口 8081 被占用：程序会自动往后找（8082、8083…），窗口里会写明实际端口。
    也可以直接指定：答题卡扫描服务.exe --port 9000
  · 想换数据目录：答题卡扫描服务.exe --data D:\asb-data
    （也认环境变量：set ASB_DATA=D:\asb-data）
  · 内网部署、多人同时用、要 HTTPS：请用 Docker 镜像版本。
  · 其它参数：答题卡扫描服务.exe --help
"@
Write-Utf8Bom (Join-Path $scanDir '使用说明.txt') $scanReadme

# ---------------------------------------------------------------- 打 zip

$zipCard = Join-Path $ReleaseDir ("answer-sheet-builder-{0}-cardmaker-windows-x64.zip" -f $Version)
$zipScan = Join-Path $ReleaseDir ("answer-sheet-builder-{0}-scanner-windows-x64.zip" -f $Version)

if (-not $SkipZip) {
    Write-Step '生成 zip'
    Add-Type -AssemblyName System.IO.Compression.FileSystem | Out-Null

    # 每个 zip 里包一层同名目录，解压出来不会散一地。
    # 用 .NET 的 ZipFile 而不是 Compress-Archive：PS 5.1 的 Compress-Archive
    # 对非 ASCII 文件名（中文目录/说明文件）会写坏条目名，.NET 默认 UTF-8 不会。
    foreach ($pair in @(
            @{ Stage = (Join-Path $StageRoot 'cardmaker'); Src = (Join-Path $ReleaseDir $DirCard); Zip = $zipCard },
            @{ Stage = (Join-Path $StageRoot 'scanner');   Src = (Join-Path $ReleaseDir $DirScan); Zip = $zipScan })) {

        New-Item -ItemType Directory -Force -Path $pair.Stage | Out-Null
        $inner = Join-Path $pair.Stage (Split-Path $pair.Src -Leaf)
        Remove-Safe $inner -Soft
        Copy-Item -Path $pair.Src -Destination $inner -Recurse -Force
        Remove-Safe $pair.Zip -Soft
        [System.IO.Compression.ZipFile]::CreateFromDirectory(
            $pair.Stage, $pair.Zip,
            [System.IO.Compression.CompressionLevel]::Optimal, $false,
            [System.Text.Encoding]::UTF8)
    }
    Remove-Safe $StageRoot -Soft
}

# 分析中间产物（扫描端那坨有几百 MB）能清就清。清不掉只是占点磁盘 —— 绝不能让构建失败。
Remove-Safe $WorkRoot -Soft

# ---------------------------------------------------------------- 汇总

Write-Step '产物'
$rows = @()
foreach ($d in @($cardDir, $scanDir)) {
    $size = (Get-ChildItem -LiteralPath $d -Recurse -File | Measure-Object -Property Length -Sum).Sum
    $rows += [pscustomobject]@{
        '目录' = (Split-Path $d -Leaf)
        '体积' = ('{0:N1} MB' -f ($size / 1MB))
    }
}
foreach ($z in @($zipCard, $zipScan)) {
    if (Test-Path -LiteralPath $z) {
        $rows += [pscustomobject]@{
            '目录' = (Split-Path $z -Leaf)
            '体积' = ('{0:N1} MB' -f ((Get-Item -LiteralPath $z).Length / 1MB))
        }
    }
}
$rows | Format-Table -AutoSize | Out-String | Write-Host

if ($env:GITHUB_STEP_SUMMARY) {
    $md = @('### 🪟 Windows 免安装版（' + $Version + '）', '')
    $md += '| 产物 | 体积 |'
    $md += '| --- | --- |'
    foreach ($r in $rows) { $md += ('| `' + $r.'目录' + '` | ' + $r.'体积' + ' |') }
    $md += ''
    $md += ('手写 CNN：' + $(if ($withCnn) { '已包含（真实手写净准确率 94.3%）' } else { '未包含（纯 OpenCV 75.5%）' }))
    $md += ''
    Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value $md -Encoding UTF8
}

Write-Host '完成。' -ForegroundColor Green
