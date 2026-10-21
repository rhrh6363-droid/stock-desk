# ===========================================================
#   새 PC 세팅 / 기존 PC 동기화 — 몇 번을 돌려도 안전하다
# ===========================================================
#   powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
#   작업 등록은 건너뛰기:  ... -NoTasks
#
#   하는 일
#     1) 파이썬 패키지 설치 (requirements.txt)
#     2) 비공개 저장소 pc-sync 를 ~\.stock-desk\pc-sync 로 받는다 (gh 로그인이 되어 있어야 한다)
#     3) 거기서 꺼내 배치한다
#          secrets.env           → ~\.stock-desk\secrets.env     (KRX · 토스 키)
#          stock-desk\config.json → 이 폴더의 config.json        (구글시트)
#          service_account.json  → ~\.stock-desk\ 로 두고 config.json 경로를 맞춘다
#          claude\skills         → ~\.claude\skills              (trading-desk 등)
#          claude\memory         → ~\.claude\projects\<프로젝트>\memory
#     4) 작업 스케줄러에 '주식 장중수집' 이 없으면 등록한다 (절전 해제 포함)
#
#   키 값은 화면에 출력하지 않는다. 키를 pc-sync 에 올리는 쪽은 scripts\export-secrets.ps1 이다.
# ===========================================================

param([switch]$NoTasks)

$ErrorActionPreference = "Stop"
$Root     = Split-Path -Parent $PSScriptRoot
$StockDir = Join-Path $env:USERPROFILE ".stock-desk"
$Sync     = Join-Path $StockDir "pc-sync"
$Repo     = "rhrh6363-droid/pc-sync"
$Claude   = Join-Path $env:USERPROFILE ".claude"

function Step($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  [OK] $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [!]  $t" -ForegroundColor Yellow }

New-Item -ItemType Directory -Force $StockDir | Out-Null

# ── 1) 파이썬
Step "파이썬 패키지"
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
if ($Python) {
    & $Python -m pip install -q -r (Join-Path $Root "requirements.txt")
    if ($LASTEXITCODE -eq 0) { Ok "pip install ($Python)" } else { Warn "pip install 실패 (종료코드 $LASTEXITCODE)" }
} else {
    Warn "파이썬을 찾을 수 없습니다. 3.12 이상을 설치한 뒤 다시 실행하세요."
}

# ── 2) pc-sync 받기
Step "비공개 저장소 pc-sync"
$synced = $false
try {
    if (Test-Path (Join-Path $Sync ".git")) {
        git -C $Sync pull --ff-only -q
    } elseif (Get-Command gh -ErrorAction SilentlyContinue) {
        gh repo clone $Repo $Sync -- -q
    } else {
        git clone -q "https://github.com/$Repo.git" $Sync
    }
    if ($LASTEXITCODE -eq 0) { $synced = $true; Ok "받았습니다: $Sync" }
} catch { }
if (-not $synced) { Warn "pc-sync 를 받지 못했습니다. gh auth status 로 로그인을 확인하세요. (아래 배치는 건너뜁니다)" }

# ── 3) 배치
if ($synced) {
    Step "파일 배치"
    $f = Join-Path $Sync "secrets.env"
    if (Test-Path $f) { Copy-Item $f (Join-Path $StockDir "secrets.env") -Force; Ok "secrets.env" }
    else { Warn "pc-sync 에 secrets.env 가 아직 없습니다 → 키가 있는 PC 에서 scripts\export-secrets.ps1 을 먼저 실행하세요" }

    $cfg = Join-Path $Sync "stock-desk\config.json"
    if (Test-Path $cfg) {
        $dstCfg = Join-Path $Root "config.json"
        Copy-Item $cfg $dstCfg -Force
        $sa = Join-Path $Sync "stock-desk\service_account.json"
        if (Test-Path $sa) {
            $saDst = Join-Path $StockDir "service_account.json"
            Copy-Item $sa $saDst -Force
            $obj = Get-Content $dstCfg -Raw -Encoding UTF8 | ConvertFrom-Json
            $obj.service_account_json = $saDst
            [IO.File]::WriteAllText($dstCfg, ($obj | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
        }
        Ok "config.json (구글시트)"
    }

    $sk = Join-Path $Sync "claude\skills"
    if (Test-Path $sk) {
        New-Item -ItemType Directory -Force (Join-Path $Claude "skills") | Out-Null
        Copy-Item (Join-Path $sk "*") (Join-Path $Claude "skills") -Recurse -Force
        Ok "Claude 스킬"
    }

    $mem = Join-Path $Sync "claude\memory"
    if (Test-Path $mem) {
        $key = (Split-Path $Root -Parent) -replace '[:\\/]', '-'      # E:\Claude → E--Claude
        $memDst = Join-Path $Claude "projects\$key\memory"
        New-Item -ItemType Directory -Force $memDst | Out-Null
        Copy-Item (Join-Path $mem "*") $memDst -Recurse -Force
        Ok "Claude 메모리 → projects\$key"
    }
}

# ── 4) 작업 스케줄러
if (-not $NoTasks) {
    Step "작업 스케줄러"
    $name = "주식 장중수집"
    # 예전 이름('장중수집')으로 이미 등록된 PC 에 또 등록하면 5분마다 두 번 돌아 커밋이 충돌한다
    $have = @($name, "장중수집") | Where-Object { Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
    if ($have) {
        Ok "'$have' 이미 등록됨 (건드리지 않음)"
    } else {
        $bat = Join-Path $Root "scripts\장중수집.bat"
        $action  = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $Root
        $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 08:55
        $rep = (New-ScheduledTaskTrigger -Once -At 08:55 -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Hours 6 -Minutes 50)).Repetition
        $trigger.Repetition = $rep
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
        $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
            -Description "장중 5분 수집 (평일 08:55~15:45) → docs/data/live.json" -Force | Out-Null
        Ok "'$name' 등록 (평일 08:55부터 5분 간격, 절전 해제)"
    }
    Write-Host "  (특징주 일일집계는 클라우드가 돌립니다. 필요하면 작업등록.ps1 을 따로 실행하세요)"
}

# ── 결과
Step "점검"
$env_ = Join-Path $StockDir "secrets.env"
$need = "KRX_ID", "KRX_PW", "TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET"
$have = @()
if (Test-Path $env_) {
    $have = Get-Content $env_ -Encoding UTF8 | ForEach-Object { if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\S') { $Matches[1] } }
}
foreach ($k in $need) {
    if ($have -contains $k) { Ok $k } else { Warn "$k 없음" }
}
Write-Host ""
