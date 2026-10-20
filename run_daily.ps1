# ===========================================================
#   일일 자동 실행 래퍼  —  작업 스케줄러가 이 파일을 호출한다
# ===========================================================
#   1) 특징주_자동집계.py   : KRX 수집 + 필터 + ADR + 엑셀 누적
#   2) sheets_push.py       : 결과를 구글시트로 전송 (config.json 있을 때만)
#   로그는 logs\ 아래 날짜별로 남고 60일 지난 것은 지운다.
#
#   손으로 실행해 볼 때:  powershell -ExecutionPolicy Bypass -File run_daily.ps1
# ===========================================================

$ErrorActionPreference = "Continue"

$Root   = Split-Path -Parent $MyInvocation.MyCommand.Path
# PC마다 파이썬 설치 경로가 달라서, 있는 것을 순서대로 찾고 없으면 PATH 의 python 을 쓴다
$Python = @(
    "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe",
    "$env:LOCALAPPDATA\Python\bin\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notmatch 'WindowsApps') { $Python = $cmd.Source }
}
$LogDir = Join-Path $Root "logs"

Set-Location $Root
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

$Stamp = Get-Date -Format "yyyyMMdd"
$Log   = Join-Path $LogDir "run_$Stamp.log"

function Write-Log {
    param([string]$Text)
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Text
    Add-Content -Path $Log -Value $line -Encoding utf8
}

Add-Content -Path $Log -Value "" -Encoding utf8
Write-Log "=== 실행 시작 ==="

if (-not (Test-Path $Python)) {
    Write-Log "[중단] 파이썬을 찾을 수 없습니다: $Python"
    exit 1
}
# PC 공용 비밀 파일 — 환경변수에 없는 키만 채운다 (scripts\bootstrap.ps1 이 만든다)
$Secrets = Join-Path $env:USERPROFILE ".stock-desk\secrets.env"
if (Test-Path $Secrets) {
    foreach ($l in Get-Content $Secrets -Encoding UTF8) {
        if ($l -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$' -and -not [Environment]::GetEnvironmentVariable($Matches[1])) {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"'), 'Process')
        }
    }
}
if (-not $env:KRX_ID -or -not $env:KRX_PW) {
    Write-Log "[중단] KRX_ID / KRX_PW 가 없습니다. scripts\bootstrap.ps1 을 실행하세요."
    exit 1
}

# ── 1) 수집
Write-Log "1/3 특징주 수집..."
$out = & $Python "특징주_자동집계.py"
$collectCode = $LASTEXITCODE
Add-Content -Path $Log -Value $out -Encoding utf8

if ($collectCode -eq 2) {
    Write-Log "휴장일이거나 데이터가 아직 반영되지 않았습니다. 전송은 건너뜁니다."
    Write-Log "=== 종료 (수집 데이터 없음) ==="
    exit 0
}
if ($collectCode -ne 0) {
    Write-Log "[실패] 수집 중단 (종료코드 $collectCode). 로그 위쪽의 원인을 확인하세요."
    Write-Log "=== 종료 (실패) ==="
    exit $collectCode
}

# ── 2) 보는 화면 생성
Write-Log "2/3 손익비 데스크 생성..."
$out = & $Python "dashboard.py"
Add-Content -Path $Log -Value $out -Encoding utf8
if ($LASTEXITCODE -ne 0) { Write-Log "[실패] 화면 생성 (종료코드 $LASTEXITCODE)" }

# ── 3) 구글시트 전송
Write-Log "3/3 구글시트 전송..."
$out = & $Python "sheets_push.py"
$pushCode = $LASTEXITCODE
Add-Content -Path $Log -Value $out -Encoding utf8

if ($pushCode -ne 0) { Write-Log "[실패] 전송 중단 (종료코드 $pushCode)" }

# ── 로그 정리
Get-ChildItem $LogDir -Filter "run_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-60) } |
    Remove-Item -Force

Write-Log "=== 실행 종료 ==="
exit $pushCode
