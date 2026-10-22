# ===========================================================
#   작업 저장소 자동 커밋·푸시 — Claude Code Stop · SessionEnd 훅
# ===========================================================
#   <루트>\.claude\settings.json 이 부른다 (workspace.ps1 이 등록, session-check.ps1 이 빠졌으면 다시 등록).
#     Stop       : 응답이 끝날 때마다 (백그라운드) — 바뀐 게 없으면 저장소마다 git status 한 번으로 끝난다
#     SessionEnd : 세션을 닫을 때 한 번 더 (Stop 이 끝나기 전에 닫혔을 때 대비)
#   대상: <루트>\stock\* · <루트>\youtube\* 중 git 저장소 전부 (코드·.md 모두)
#   빼는 것:
#     - stock-desk 의 app/data · docs/data — 장중수집·오전집계가 5분마다 직접 커밋한다 (겹치면 충돌)
#     - *.err · *.log · *.tmp — 실행 잔해
#     - 키처럼 보이는 파일·내용 — stock-desk 는 공개 저장소다. 걸리면 그 저장소는 커밋하지 않고 기록만 남긴다
#   충돌(pull --rebase 실패)이면 커밋은 로컬에 두고 다음 번에 다시 올린다. 항상 종료코드 0 (세션을 막지 않는다)
#   기록: %USERPROFILE%\.stock-desk\auto-commit.log  (저장소 밖 — 기록이 다시 커밋되지 않게)
# ===========================================================

$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent $PSScriptRoot
$Root = Split-Path -Parent (Split-Path -Parent $Repo)               # <루트>\stock\stock-desk → <루트>
$logDir = Join-Path $env:USERPROFILE ".stock-desk"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "auto-commit.log"
function Log($s) { try { Add-Content -Path $log -Encoding UTF8 -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $s" } catch {} }
function G($p) { & git.exe -C $p @args 2>&1 | Out-String }

# 여러 세션이 동시에 끝나도 한 번에 하나만
$mx = New-Object Threading.Mutex($false, "Local\ws-auto-commit")
if (-not $mx.WaitOne(90000)) { Log "skip: 다른 자동 커밋이 아직 도는 중"; exit 0 }
try {
    $repos = foreach ($g in "stock", "youtube") {
        $d = Join-Path $Root $g
        if (Test-Path $d) { Get-ChildItem -LiteralPath $d -Directory | Where-Object { Test-Path (Join-Path $_.FullName ".git") } }
    }
    $badName = '(^|/)(secrets\.env|config\.json|toss_token\.json|.*service[_-]?account.*\.json|.*\.pem|.*\.p12|.*\.key)$'
    $badText = '-----BEGIN [A-Z ]*PRIVATE KEY|"private_key"\s*:|(?i)\b[A-Z_]*(SECRET|APP_?KEY|API_?KEY|PASSWORD|_PW)\b\s*[=:]\s*["'']?[A-Za-z0-9/+_\-]{12,}'
    foreach ($r in $repos) {
        $p = $r.FullName; $name = $r.Name
        if (Test-Path (Join-Path $p ".git\index.lock")) { Log "$name skip: index.lock (다른 git 작업 중)"; continue }
        if ((Test-Path (Join-Path $p ".git\rebase-merge")) -or (Test-Path (Join-Path $p ".git\rebase-apply"))) { Log "$name skip: rebase 진행 중 — 손으로 정리 필요"; continue }
        $spec = @(".", ":(exclude)*.err", ":(exclude)*.log", ":(exclude)*.tmp")
        if ($name -eq "stock-desk") { $spec += ":(exclude)app/data", ":(exclude)docs/data" }
        $dirty = (& git.exe -C $p status --porcelain -- @spec 2>$null)
        if ($dirty) {
            G $p add -A -- @spec | Out-Null
            $files = @(& git.exe -C $p diff --cached --name-only 2>$null)
            if ($files.Count -gt 0) {
                $hitName = @($files | Where-Object { $_ -match $badName })
                $hitText = (& git.exe -C $p diff --cached -U0 2>$null | Where-Object { $_ -like "+*" -and $_ -notlike "+++*" } | Select-String -Pattern $badText -Quiet)
                if ($hitName.Count -gt 0 -or $hitText) {
                    G $p reset -q | Out-Null
                    Log "$name STOP: 키로 보이는 파일·내용이 있어 커밋하지 않음 → $($hitName -join ', ') $(if($hitText){'(내용에 키 패턴)'})"
                    continue
                }
                $msg = "auto: $env:COMPUTERNAME $(Get-Date -Format 'yyyy-MM-dd HH:mm') — $($files.Count)개 파일"
                $out = G $p commit -q -m $msg
                Log "$name commit $($files.Count)개 $($out.Trim())"
            }
        }
        # 안 올린 커밋이 있으면 올린다 (이번에 만든 것 + 지난번 충돌로 남은 것)
        $ahead = (& git.exe -C $p rev-list --count "@{u}..HEAD" 2>$null)
        if ($ahead -and [int]$ahead -gt 0) {
            $pl = G $p -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=15 pull --rebase --autostash -q
            if ($LASTEXITCODE -ne 0) {
                G $p rebase --abort | Out-Null
                Log "$name pull 실패(충돌?) — 커밋은 로컬에 두고 다음에 다시: $($pl.Trim())"; continue
            }
            $ps = G $p push -q
            Log "$name push rc=$LASTEXITCODE ($ahead커밋) $($ps.Trim())"
        }
    }
} catch { Log "error: $_" }
finally { $mx.ReleaseMutex() }
exit 0
