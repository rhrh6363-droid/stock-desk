# ===========================================================
#   Claude Code SessionStart 훅 — 세션이 열릴 때마다 PC 상태를 점검한다
# ===========================================================
#   .claude\settings.json 이 부른다. 출력은 세션 첫머리 맥락으로 들어간다.
#   조용해야 하므로 문제가 있을 때만 말하고, 느린 일은 하지 않는다.
#   실패해도 세션을 막지 않는다 (항상 종료코드 0).
# ===========================================================

$ErrorActionPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$msg = @()

# 1) 최신 코드 — 로컬에 안 올린 커밋이 있으면 건너뛴다
$before = git rev-parse HEAD
git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=8 pull --ff-only -q 2>$null
$after = git rev-parse HEAD
if ($before -ne $after) { $msg += "코드를 최신으로 받았습니다 ($(git rev-list --count $before..$after)커밋)." }

# 2) 키 파일
$sec = Join-Path $env:USERPROFILE ".stock-desk\secrets.env"
$need = "KRX_ID", "KRX_PW", "TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET"
$have = @()
if (Test-Path $sec) {
    $have = Get-Content $sec -Encoding UTF8 | ForEach-Object { if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\S') { $Matches[1] } }
}
$missing = @($need | Where-Object { ($have -notcontains $_) -and -not [Environment]::GetEnvironmentVariable($_, 'User') })
if ($missing.Count -gt 0) {
    $msg += "[설정 필요] 이 PC에 키가 없습니다: $($missing -join ', '). 사용자에게 묻지 말고 scripts\bootstrap.ps1 을 실행하세요 (pc-sync 에서 받아옵니다). pc-sync 에도 없으면 키가 있는 PC 에서 scripts\export-secrets.ps1 을 먼저 실행해야 합니다."
}

# 3) 스케줄러
$t = Get-ScheduledTask -TaskName "주식 장중수집"
if (-not $t) { $msg += "[설정 필요] 작업 스케줄러에 '주식 장중수집' 이 없습니다 → scripts\bootstrap.ps1" }
elseif (-not $t.Settings.WakeToRun) { $msg += "'주식 장중수집' 의 절전 해제(WakeToRun)가 꺼져 있습니다. 절전 중에는 수집이 비니 확인하세요." }

if ($msg.Count -gt 0) { "PC 점검:"; $msg | ForEach-Object { "- $_" } }
exit 0
