# ===========================================================
#   작업 폴더 구조 맞추기 — 두 PC 가 같은 구조를 쓰게 강제한다. 몇 번을 돌려도 안전하다
# ===========================================================
#   <루트>\                      (이 PC: D:\github, 다른 PC: E:\Claude 등 — 루트 이름은 PC 마다 달라도 된다)
#     CLAUDE.md                  ← 이 스크립트가 scripts\workspace\ROOT_CLAUDE.md 로 덮어쓴다
#     .claude\settings.json      ← SessionStart 훅(session-check.ps1) · Stop/SessionEnd 훅(auto-commit.ps1 — 작업 저장소 자동 커밋·푸시)
#     stock\   stock-desk · backtest · simulation
#     youtube\ youtube · siyun
#   주식·유튜브가 아닌 것(SAP 등)은 루트에 두지 않는다 → D:\work 같은 다른 폴더로.
#
#   실행 (stock-desk 폴더 '밖'에서 — 자기 폴더는 옮길 수 없다)
#     powershell -NoProfile -ExecutionPolicy Bypass -File <stock-desk>\scripts\workspace.ps1
#       옛 폴더(stock-desk·trading·BACKTEST·SIMULATION·유튜브·siyun 이 루트 바로 아래)를 제자리로 옮기고,
#       없는 저장소는 받고, 작업 스케줄러의 옛 경로를 새 경로로 바꾼다.
#     ... -Check   옮기지 않고 문제만 출력한다 (session-check.ps1 · bootstrap.ps1 이 부른다). 문제 없으면 출력 없음
#     ... -Root E:\Claude   루트를 직접 지정 (기본: 이 스크립트 위치로 추정)
#     ... -Hooks   루트 CLAUDE.md · .claude\settings.json 훅만 다시 쓴다 (session-check.ps1 이 훅이 빠졌을 때 부른다)
#
#   이 스크립트는 git 저장소를 지우지 않는다. 같은 저장소의 중복 사본(옛 'trading')은 <루트>\_삭제예정 으로 옮긴다.
# ===========================================================

param([string]$Root, [switch]$Check, [switch]$Hooks)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot                     # 지금 stock-desk 가 있는 곳

# 루트 추정: <루트>\stock\stock-desk 면 두 단계 위, 옛 구조(<루트>\stock-desk)면 한 단계 위
if (-not $Root) {
    $up = Split-Path -Parent $Repo
    if ((Split-Path -Leaf $up) -eq "stock") { $Root = Split-Path -Parent $up } else { $Root = $up }
}
$Root = (Resolve-Path $Root).Path.TrimEnd('\')

# 구조 정의 — 바꿀 때는 이 표와 ROOT_CLAUDE.md 를 같이 고친다
$Layout = @(
    @{ group = "stock";   name = "stock-desk"; repo = "rhrh6363-droid/stock-desk"; old = @("stock-desk", "trading") },
    @{ group = "stock";   name = "backtest";   repo = "rhrh6363-droid/backtest";   old = @("BACKTEST") },      # 대소문자 구분 없음
    @{ group = "stock";   name = "simulation"; repo = "rhrh6363-droid/simulation"; old = @("SIMULATION") },
    @{ group = "youtube"; name = "youtube";    repo = "rhrh6363-droid/youtube";    old = @("유튜브", "youtube") },
    @{ group = "youtube"; name = "siyun";      repo = "rhrh6363-droid/siyun";      old = @("siyun") }
)
$Allowed = @("stock", "youtube", "CLAUDE.md", ".claude", "_삭제예정")

function Target($e) { Join-Path $Root "$($e.group)\$($e.name)" }
function IsDir($p)  { Test-Path -LiteralPath $p -PathType Container }
# 정상 저장소인가 (반쯤 옮겨진 잔해는 .git 폴더만 있고 HEAD 가 없다)
function Git-Out($p) { $ea = $ErrorActionPreference; $ErrorActionPreference = "Continue"; $o = & git -C $p @args 2>$null; $ErrorActionPreference = $ea; $o }
function IsRepo($p) { (Test-Path -LiteralPath (Join-Path $p ".git")) -and [bool](Git-Out $p rev-parse --verify -q HEAD) }
# 원격에 없는 것이 있는가 — 변경·git 제외 파일(output/·cache/·config.json 등)·stash·안 올린 커밋.
# git 이 아닌 폴더(옛 BACKTEST 등)는 파일이 있으면 있다고 본다. 잔해(.git 만 있고 HEAD 없음)는 없다고 본다.
function HasLocal($p) {
    if (-not (IsRepo $p)) {
        if (Test-Path -LiteralPath (Join-Path $p ".git")) { return $false }
        return [bool](Get-ChildItem -LiteralPath $p -Force)
    }
    [bool]((Git-Out $p status --porcelain --ignored) -or (Git-Out $p stash list) -or (Git-Out $p log --branches --not --remotes --oneline))
}
# 옛 위치 = 루트 바로 아래의 그 이름 폴더. 단 <루트>\youtube 는 새 구조의 묶음 폴더이기도 해서, 저장소(.git)일 때만 옛 위치로 본다
function IsOld($p)  { (IsDir $p) -and ((Test-Path -LiteralPath (Join-Path $p ".git")) -or ($Allowed -notcontains (Split-Path -Leaf $p))) }

# ── 점검: 문제 목록을 만든다
function Find-Problems {
    $p = @()
    foreach ($e in $Layout) {
        $t = Target $e
        $olds = @($e.old | ForEach-Object { Join-Path $Root $_ } | Where-Object { IsOld $_ })
        if ($olds) { $p += "옛 위치에 있음: $($olds -join ', ') → $t" }
        elseif (-not (IsDir $t)) { $p += "없음: $t ($($e.repo))" }
    }
    $oldNames = $Layout | ForEach-Object { $_.old }
    $stray = Get-ChildItem -LiteralPath $Root -Force | Where-Object { $Allowed -notcontains $_.Name -and $oldNames -notcontains $_.Name }
    foreach ($s in $stray) { $p += "루트에 분류 안 된 항목: $($s.FullName) (주식·유튜브가 아니면 루트 밖으로, 맞으면 stock\ 이나 youtube\ 아래로)" }
    $p
}

if ($Check) {
    $p = @(Find-Problems)
    if ($p.Count -gt 0) {
        "[구조 변경 필요] 작업 폴더가 정해진 구조(<루트>\stock\…, <루트>\youtube\…)와 다릅니다. 다른 작업보다 먼저 맞추세요."
        $p | ForEach-Object { "  - $_" }
        "  → stock-desk 폴더 밖에서 실행: powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Root `"$Root`""
        "    (git 폴더 이동은 Claude 샌드박스가 막으므로, 사용자가 ! 로 직접 실행해야 할 수 있다)"
    }
    exit 0
}

function Step($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  [OK] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [!]  $t" -ForegroundColor Yellow }

Set-Location $Root                                               # 옮길 폴더 안에 있으면 이름을 못 바꾼다
Write-Host "루트: $Root"

if (-not $Hooks) {                                               # -Hooks 면 1)·2) 를 건너뛰고 훅만 쓴다
# ── 1) 옮기기 / 받기
Step "폴더"
$moved = @{}                                                     # 옛 경로 → 새 경로 (작업 스케줄러 고칠 때 쓴다)
foreach ($e in $Layout) {
    $t = Target $e
    $failed = $false
    $trash = Join-Path $Root "_삭제예정"
    foreach ($o in $e.old) {
        $src = Join-Path $Root $o
        if (-not (IsOld $src)) { continue }
        if (IsDir $t) {
            # 제자리와 옛 위치에 둘 다 있다 — 원격에 없는 것이 있는 쪽을 살리고, 나머지는 _삭제예정 으로
            $keepOld = HasLocal $src
            $keepNew = HasLocal $t
            if ($keepOld -and $keepNew) { Warn "$src 와 $t 둘 다 원격에 없는 내용이 있어 그대로 둡니다. 확인 후 직접 정리하세요."; $failed = $true; break }
            New-Item -ItemType Directory -Force $trash | Out-Null
            $stamp = Get-Date -Format yyyyMMddHHmmss
            try {
                if ($keepOld) {
                    [IO.Directory]::Move($t, (Join-Path $trash "$($e.name)-새클론-$stamp"))
                    [IO.Directory]::Move($src, $t)
                    Ok "$src → $t (제자리에 있던 새 클론은 _삭제예정)"
                } else {
                    [IO.Directory]::Move($src, (Join-Path $trash "$o-$stamp"))
                    Ok "중복 사본 $src → _삭제예정 (확인 후 지우세요)"
                }
            } catch { Warn "옮기기 실패 $src : $($_.Exception.InnerException.Message) (Claude Code·탐색기·VS Code·터미널을 모두 닫고 새 PowerShell 창에서 다시)"; $failed = $true; break }
            $moved[$src] = $t
        } else {
            try {
                # <루트>\youtube(저장소) → <루트>\youtube\youtube 처럼 자기 안으로 옮길 때는 임시 이름을 거친다
                $tmp = Join-Path $Root ".ws-tmp-$($e.name)"
                [IO.Directory]::Move($src, $tmp)
                New-Item -ItemType Directory -Force (Split-Path -Parent $t) | Out-Null
                [IO.Directory]::Move($tmp, $t)
            } catch {
                if ((IsDir $tmp) -and -not (IsDir $src)) { [IO.Directory]::Move($tmp, $src) }   # 반쯤 옮긴 상태로 두지 않는다
                # 실패하면 이 저장소는 여기서 멈춘다 — 다음 후보(예: 중복 사본)를 대신 옮기거나 새로 받지 않는다
                Warn "옮기기 실패 $src → $t : $($_.Exception.InnerException.Message) (Claude Code·탐색기·VS Code·터미널을 모두 닫고 새 PowerShell 창에서 다시)"; $failed = $true; break
            }
            $moved[$src] = $t
            Ok "$src → $t"
        }
    }
    if (-not $failed -and -not (IsDir $t)) {
        New-Item -ItemType Directory -Force (Split-Path -Parent $t) | Out-Null
        gh repo clone $e.repo $t -- -q
        if ($LASTEXITCODE -eq 0) { Ok "받음: $t" } else { Warn "받기 실패: $($e.repo) (gh auth status 확인)" }
    }
}

# ── 2) 작업 스케줄러: 옛 경로를 새 경로로
Step "작업 스케줄러"
$fixed = 0
foreach ($task in Get-ScheduledTask | Where-Object { $_.TaskPath -eq "\" }) {
    $changed = $false
    foreach ($a in $task.Actions) {
        foreach ($k in $moved.Keys) {
            $rx = [regex]::Escape($k) + '(?=\\|"|$)'
            foreach ($f in "Execute", "Arguments", "WorkingDirectory") {
                if ($a.$f -and $a.$f -match $rx) { $a.$f = [regex]::Replace($a.$f, $rx, $moved[$k].Replace('$', '$$'), 'IgnoreCase'); $changed = $true }
            }
        }
    }
    if ($changed) { Set-ScheduledTask -TaskName $task.TaskName -Action $task.Actions | Out-Null; $fixed++; Ok "$($task.TaskName) 경로 수정" }
}
if ($fixed -eq 0) { Ok "고칠 작업 없음" }

}

# ── 3) 루트 안내문 + 훅 (SessionStart 점검 · Stop/SessionEnd 자동 커밋)
Step "루트 CLAUDE.md · 세션 점검 훅"
$sd = Target $Layout[0]
$tpl = Join-Path $sd "scripts\workspace\ROOT_CLAUDE.md"
if (Test-Path $tpl) { Copy-Item $tpl (Join-Path $Root "CLAUDE.md") -Force; Ok "CLAUDE.md" }
$cfgDir = Join-Path $Root ".claude"
New-Item -ItemType Directory -Force $cfgDir | Out-Null
$checkPs = Join-Path $sd "scripts\session-check.ps1"            # $check 는 -Check 스위치와 이름이 겹친다(대소문자 무시)
$autoPs  = Join-Path $sd "scripts\auto-commit.ps1"
function Hook($ps, $t, [switch]$Async) { "{ `"hooks`": [ { `"type`": `"command`", `"shell`": `"powershell`", `"timeout`": $t,$(if($Async){' "async": true,'})`n          `"command`": `"powershell -NoProfile -ExecutionPolicy Bypass -File \`"$($ps.Replace('\','\\'))\`"`" } ] }" }
$hook = @"
{
  "hooks": {
    "SessionStart": [
      $(Hook $checkPs 30)
    ],
    "Stop": [
      $(Hook $autoPs 120 -Async)
    ],
    "SessionEnd": [
      $(Hook $autoPs 60)
    ]
  }
}
"@
$cfg = Join-Path $cfgDir "settings.json"
if ((Test-Path $cfg) -and ((Get-Content $cfg -Raw) -notmatch 'session-check\.ps1')) {
    Warn "$cfg 가 이미 있어 덮어쓰지 않았습니다. 훅(SessionStart → $checkPs, Stop·SessionEnd → $autoPs)을 직접 추가하세요."
} else {
    [IO.File]::WriteAllText($cfg, $hook, (New-Object Text.UTF8Encoding $false)); Ok ".claude\settings.json (SessionStart → session-check · Stop·SessionEnd → auto-commit)"
}
# 저장소 안 스킬(.claude\skills\*)은 하나씩, 에이전트 폴더(.claude\agents)는 통째로 루트 .claude 에 정션으로 건다
# — 세션을 루트에서 열면 하위 저장소의 것은 목록에 안 잡힌다(youtube 의 /script-draft · /script-review 등).
#   에이전트 폴더는 한 저장소(지금 youtube)만 가질 수 있다 — 둘째 저장소가 생기면 경고한다
foreach ($repo in $Layout) {
    $rc = Join-Path (Target $repo) ".claude"
    $src = Join-Path $rc "skills"
    if (Test-Path $src) {
        $dst = Join-Path $cfgDir "skills"; New-Item -ItemType Directory -Force $dst | Out-Null
        Get-ChildItem $src -Directory | ForEach-Object {
            $l = Join-Path $dst $_.Name
            if (-not (Test-Path $l)) { New-Item -ItemType Junction -Path $l -Target $_.FullName | Out-Null; Ok "스킬 연결 $($_.Name)" }
        }
    }
    $src = Join-Path $rc "agents"
    if (Test-Path $src) {
        $l = Join-Path $cfgDir "agents"
        if (-not (Test-Path $l)) { New-Item -ItemType Junction -Path $l -Target $src | Out-Null; Ok "에이전트 연결 $($repo.name)" }
        elseif ((Get-Item $l).Target -notcontains $src) { Warn "$l 이 이미 다른 곳을 가리켜 $src 를 연결하지 못했습니다" }
    }
}
if ($Hooks) { exit 0 }

# ── 결과
Step "점검"
$p = @(Find-Problems)
if ($p.Count -eq 0) { Ok "구조 정상" } else { $p | ForEach-Object { Warn $_ } }
Write-Host ""
