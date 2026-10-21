@echo off
REM ───────────────────────────────────────────────────────────
REM  특징주 일배치 (오전 보강) — 작업 스케줄러가 이 파일을 부른다.
REM  GitHub 크론이 오전에 안 돌아서 화면이 전날 기준으로 남는 것을 막는다.
REM  기록은 scripts\일배치.log 에 쌓인다 (깃에는 올라가지 않는다).
REM ───────────────────────────────────────────────────────────
cd /d "%~dp0.."
echo [%date% %time%] >> "%~dpn0.log"
set "PY="
for %%P in ("%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" "%LOCALAPPDATA%\Python\bin\python.exe" "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe") do if not defined PY if exist %%P set "PY=%%~P"
if not defined PY set "PY=python"
set PYTHONUTF8=1
"%PY%" app\run_batch.py >> "%~dpn0.log" 2>&1
