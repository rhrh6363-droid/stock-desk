# ===========================================================
#   이 PC 의 키 · 설정 · 스킬을 비공개 저장소 pc-sync 로 올린다
# ===========================================================
#   키가 있는 PC 에서 한 번만 돌리면 된다. 다른 PC 는 bootstrap.ps1 로 받는다.
#   powershell -ExecutionPolicy Bypass -File scripts\export-secrets.ps1
#
#   올리는 것
#     secrets.env        환경변수(User) 또는 ~\.stock-desk\secrets.env 에 있는 키들
#                        KRX_ID KRX_PW TOSS_CLIENT_ID TOSS_CLIENT_SECRET NAVER_ID NAVER_SECRET ANTHROPIC_API_KEY
#                        비어 있는 값은 pc-sync 에 이미 있는 값을 덮어쓰지 않는다
#     stock-desk\config.json, service_account.json   구글시트 (있을 때만)
#     claude\skills, claude\memory                   Claude 스킬·메모리
#
#   키 값은 화면에 출력하지 않는다. pc-sync 는 반드시 비공개(private) 저장소여야 한다.
# ===========================================================

$ErrorActionPreference = "Stop"
$Root     = Split-Path -Parent $PSScriptRoot
$StockDir = Join-Path $env:USERPROFILE ".stock-desk"
$Sync     = Join-Path $StockDir "pc-sync"
$Repo     = "rhrh6363-droid/pc-sync"
$Claude   = Join-Path $env:USERPROFILE ".claude"
$Names    = "KRX_ID", "KRX_PW", "TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET", "NAVER_ID", "NAVER_SECRET", "ANTHROPIC_API_KEY"

function Ok($t)   { Write-Host "  [OK] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [!]  $t" -ForegroundColor Yellow }

# 공개 저장소로 키를 올리는 사고를 막는다
$vis = gh repo view $Repo --json visibility --jq .visibility
if ($vis -ne "PRIVATE") { throw "$Repo 가 비공개가 아닙니다 ($vis). 중단합니다." }

New-Item -ItemType Directory -Force $StockDir | Out-Null
if (Test-Path (Join-Path $Sync ".git")) { git -C $Sync pull --ff-only -q }
else { gh repo clone $Repo $Sync -- -q }

# ── secrets.env : 기존 값 ← 이 PC 의 값(비어 있지 않은 것만)
$vals = [ordered]@{}
$pairs = @()
$pairs += Get-Content (Join-Path $Sync "secrets.env") -Encoding UTF8 -ErrorAction SilentlyContinue
$pairs += Get-Content (Join-Path $StockDir "secrets.env") -Encoding UTF8 -ErrorAction SilentlyContinue
foreach ($l in $pairs) {
    if ($l -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$' -and $Names -contains $Matches[1]) {
        $vals[$Matches[1]] = $Matches[2].Trim('"')
    }
}
foreach ($n in $Names) {
    foreach ($scope in 'Process', 'User') {
        $v = [Environment]::GetEnvironmentVariable($n, $scope)
        if ($v -and $v -ne "CHANGEME") { $vals[$n] = $v; break }
    }
}
$text = ($vals.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "`r`n"
$utf8 = New-Object Text.UTF8Encoding $false
[IO.File]::WriteAllText((Join-Path $Sync "secrets.env"), $text + "`r`n", $utf8)
[IO.File]::WriteAllText((Join-Path $StockDir "secrets.env"), $text + "`r`n", $utf8)
foreach ($n in $Names) { if ($vals.Contains($n)) { Ok $n } else { Warn "$n 없음 (이 PC 에도 pc-sync 에도 없었습니다)" } }

# ── 구글시트 설정
$cfg = Join-Path $Root "config.json"
if (Test-Path $cfg) {
    New-Item -ItemType Directory -Force (Join-Path $Sync "stock-desk") | Out-Null
    Copy-Item $cfg (Join-Path $Sync "stock-desk\config.json") -Force
    $o = Get-Content $cfg -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($o.service_account_json -and (Test-Path $o.service_account_json)) {
        Copy-Item $o.service_account_json (Join-Path $Sync "stock-desk\service_account.json") -Force
        Ok "config.json + 서비스 계정 키"
    } else {
        Ok "config.json (서비스 계정 키 파일은 경로가 비어 있거나 없어서 건너뜀)"
    }
}

# ── Claude 스킬 · 메모리
$sk = Join-Path $Claude "skills\trading-desk"
if (Test-Path $sk) {
    New-Item -ItemType Directory -Force (Join-Path $Sync "claude\skills") | Out-Null
    Copy-Item $sk (Join-Path $Sync "claude\skills") -Recurse -Force
    Ok "스킬 trading-desk"
}
$key = (Split-Path $Root -Parent) -replace '[:\\/]', '-'
$mem = Join-Path $Claude "projects\$key\memory"
if (Test-Path $mem) {
    New-Item -ItemType Directory -Force (Join-Path $Sync "claude\memory") | Out-Null
    Copy-Item (Join-Path $mem "*") (Join-Path $Sync "claude\memory") -Recurse -Force
    Ok "메모리 ($key)"
}

# ── 올리기
git -C $Sync add -A
git -C $Sync diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Write-Host "`n변경 없음 — 이미 최신입니다."; exit 0 }
git -C $Sync -c user.name="$env:USERNAME" -c user.email="rhrh6363@gmail.com" commit -q -m "sync $env:COMPUTERNAME $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
git -C $Sync branch -M main
git -C $Sync push -q -u origin main
if ($LASTEXITCODE -eq 0) { Write-Host "`n올렸습니다. 다른 PC 에서 scripts\bootstrap.ps1 을 실행하면 됩니다." -ForegroundColor Green }
else { Write-Host "`npush 실패" -ForegroundColor Red; exit 1 }
