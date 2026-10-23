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
#          claude\skills·hooks·memory → ~\.claude 의 같은 폴더를 pc-sync 로 정션 연결 (claude\hooks\claude-sync.ps1 link)
#            연결 뒤에는 세션 시작 때 자동 pull, 응답이 끝날 때 바뀐 것만 자동 commit·push 한다
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

# ── 0) 폴더 구조 — stock-desk 는 <루트>\stock\stock-desk 에 있어야 한다 (scripts\workspace.ps1, <루트>\CLAUDE.md)
$Up = Split-Path -Parent $Root
if ((Split-Path -Leaf $Up) -ne "stock") {
    Write-Host ""
    Write-Host "[구조 변경 필요] stock-desk 가 옛 위치($Root)에 있습니다. 먼저 이 폴더 밖에서 구조를 맞추세요:" -ForegroundColor Red
    Write-Host "  cd $Up"
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\workspace.ps1`""
    Write-Host "  그다음 <루트>\stock\stock-desk\scripts\bootstrap.ps1 을 다시 실행합니다."
    exit 1
}
$WsRoot = Split-Path -Parent $Up                                   # 작업 루트 (D:\github, E:\Claude …)
Step "폴더 구조"
& (Join-Path $PSScriptRoot "workspace.ps1") -Root $WsRoot          # 없는 저장소 받기 · 루트 CLAUDE.md · 세션 점검 훅

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

    # Claude 스킬·훅(완료 팝업·세션명·자동 동기화)·메모리 — 복사가 아니라 pc-sync 로 연결한다
    $link = Join-Path $Sync "claude\hooks\claude-sync.ps1"
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Warn "node 가 없어 Claude 설정 연결을 건너뜁니다. Node.js 설치 후 다시 실행하세요."
    } elseif (Test-Path $link) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $link link -WsRoot $WsRoot   # 메모리: E:\Claude → projects\E--Claude
        if ($LASTEXITCODE -eq 0) { Ok "Claude 스킬·훅·메모리 연결 (이후 자동 동기화)" } else { Warn "Claude 설정 연결 실패 (종료코드 $LASTEXITCODE)" }
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
        # .bat 를 직접 걸면 5분마다 검은 창이 뜬다 — wscript //B 로 장중수집.vbs(창 없이 .bat 실행)를 부른다
        $vbs = Join-Path $Root "scripts\장중수집.vbs"
        $action  = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "//B //Nologo `"$vbs`"" -WorkingDirectory $Root
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
