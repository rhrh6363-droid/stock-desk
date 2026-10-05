# ===========================================================
#   작업 스케줄러 등록 / 해제 / 상태 확인
# ===========================================================
#   등록 :  powershell -ExecutionPolicy Bypass -File 작업등록.ps1
#   시간 :  powershell -ExecutionPolicy Bypass -File 작업등록.ps1 -At 16:30
#   해제 :  powershell -ExecutionPolicy Bypass -File 작업등록.ps1 -Remove
#   상태 :  powershell -ExecutionPolicy Bypass -File 작업등록.ps1 -Status
#
#   관리자 권한이 필요하지 않다. 로그인한 사용자 작업으로 등록된다.
#   (그래서 setx 로 넣은 KRX_ID / KRX_PW 를 그대로 물려받는다)
# ===========================================================

param(
    [string]$At = "16:10",
    [switch]$Remove,
    [switch]$Status
)

$TaskName = "특징주 일일집계"
$Root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script   = Join-Path $Root "run_daily.ps1"

if ($Status) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) { "등록되어 있지 않습니다."; exit 0 }
    $task | Select-Object TaskName, State | Format-List
    Get-ScheduledTaskInfo -TaskName $TaskName |
        Select-Object LastRunTime, LastTaskResult, NextRunTime | Format-List
    exit 0
}

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    "해제했습니다: $TaskName"
    exit 0
}

if (-not (Test-Path $Script)) { "[중단] run_daily.ps1 을 찾을 수 없습니다."; exit 1 }

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$Script`"" `
    -WorkingDirectory $Root

$trigger = New-ScheduledTaskTrigger `
    -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At

# StartWhenAvailable: 그 시각에 PC 가 꺼져 있었으면 켜진 뒤 한 번 따라 실행한다
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "KRX 특징주 수집 + ADR 산출 + 구글시트 전송. 평일 $At." `
    -Force | Out-Null

"등록 완료: $TaskName   평일 $At"
Get-ScheduledTaskInfo -TaskName $TaskName | Select-Object NextRunTime | Format-List
