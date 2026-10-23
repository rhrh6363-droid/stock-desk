# ===========================================================
#   Claude Code SessionStart 훅 — 세션이 열릴 때마다 PC 상태를 점검한다
# ===========================================================
#   <루트>\.claude\settings.json 이 부른다 (workspace.ps1 이 등록). 출력은 세션 첫머리 맥락으로 들어간다.
#   조용해야 하므로 문제가 있을 때만 말하고, 느린 일은 하지 않는다.
#   실패해도 세션을 막지 않는다 (항상 종료코드 0).
# ===========================================================

$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = New-Object Text.UTF8Encoding $false   # 훅 출력이 한글로 읽히게 (기본 CP949 면 깨진다)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$msg = @()

# 0) 폴더 구조 — 두 PC 가 같은 구조여야 한다 (scripts\workspace.ps1)
$ws = & (Join-Path $PSScriptRoot "workspace.ps1") -Check
if ($ws) { $ws }

# 0-1) 루트 훅 — 자동 커밋(auto-commit.ps1)이 빠져 있으면 다시 쓴다 (다른 PC 에 새 훅을 퍼뜨리는 길)
$rootCfg = Join-Path (Split-Path -Parent (Split-Path -Parent $Root)) ".claude\settings.json"
if ((Test-Path $rootCfg) -and ((Get-Content $rootCfg -Raw) -match 'session-check\.ps1') -and ((Get-Content $rootCfg -Raw) -notmatch 'auto-commit\.ps1')) {
    & (Join-Path $PSScriptRoot "workspace.ps1") -Hooks *> $null
    $msg += "루트 훅에 자동 커밋(Stop·SessionEnd → auto-commit.ps1)을 추가했습니다. 다음 세션부터 적용됩니다."
}

# 1) 최신 코드 — 로컬에 안 올린 커밋이 있으면 건너뛴다
$before = git rev-parse HEAD
git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=8 pull --ff-only -q 2>$null
$after = git rev-parse HEAD
if ($before -ne $after) { $msg += "코드를 최신으로 받았습니다 ($(git rev-list --count $before..$after)커밋)." }

# 2) 키 파일 — 키의 원본은 GitHub Actions Secrets(클라우드 수집용, 다시 읽을 수 없음)와 pc-sync 의 secrets.env 다.
#    로컬에 키가 없어도 장중수집은 네이버로 돈다(토스 분봉만 빠진다). 그래서 bootstrap 으로 고쳐지는 경우에만 알린다.
function KeysIn($f) { if (Test-Path $f) { Get-Content $f -Encoding UTF8 | ForEach-Object { if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\S') { $Matches[1] } } } }
$need = "KRX_ID", "KRX_PW", "TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET"
$have = @(KeysIn (Join-Path $env:USERPROFILE ".stock-desk\secrets.env"))
$sync = @(KeysIn (Join-Path $env:USERPROFILE ".stock-desk\pc-sync\secrets.env"))
$missing = @($need | Where-Object { ($have -notcontains $_) -and -not [Environment]::GetEnvironmentVariable($_, 'User') })
$fixable = @($missing | Where-Object { $sync -contains $_ })
if ($fixable.Count -gt 0) {
    $msg += "[설정 필요] pc-sync 에는 있는데 이 PC 에 없는 키: $($fixable -join ', '). 사용자에게 묻지 말고 scripts\bootstrap.ps1 을 실행하세요."
}

# 3) 스케줄러 (예전 이름 '장중수집' 도 인정)
$t = @("주식 장중수집", "장중수집") | ForEach-Object { Get-ScheduledTask -TaskName $_ } | Select-Object -First 1
if (-not $t) { $msg += "[설정 필요] 작업 스케줄러에 '주식 장중수집' 이 없습니다 → scripts\bootstrap.ps1" }
elseif ($t.State -eq "Disabled") { $msg += "작업 스케줄러 '$($t.TaskName)' 이 꺼져 있습니다(사용 안 함). 장중 5분 수집이 안 돕니다." }
elseif (-not $t.Settings.WakeToRun) { $msg += "'$($t.TaskName)' 의 절전 해제(WakeToRun)가 꺼져 있습니다. 절전 중에는 수집이 비니 확인하세요." }

# 4) .bat / powershell 을 스케줄러에 직접 걸면 5분마다 검은 창이 뜬다 → 창 없는 wscript+.vbs 로 되돌린다
$StockRoot = Split-Path -Parent $PSScriptRoot
$hide = @{ "주식 장중수집" = (Join-Path $StockRoot "scripts\장중수집.vbs"); "특징주 일일집계" = (Join-Path $StockRoot "run_daily.vbs") }
foreach ($n in $hide.Keys) {
    $task = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if ($task -and $task.Actions[0].Execute -notmatch 'wscript' -and (Test-Path $hide[$n])) {
        try {
            Set-ScheduledTask -TaskName $n -Action (New-ScheduledTaskAction -Execute "wscript.exe" -Argument "//B //Nologo `"$($hide[$n])`"" -WorkingDirectory $StockRoot) | Out-Null
            $msg += "'$n' 이 창이 뜨는 방식으로 등록돼 있어 wscript(창 없음)로 고쳤습니다."
        } catch { $msg += "'$n' 을 창 없는 방식으로 고치지 못했습니다: $($_.Exception.Message)" }
    }
}

if ($msg.Count -gt 0) { "PC 점검:"; $msg | ForEach-Object { "- $_" } }
exit 0
