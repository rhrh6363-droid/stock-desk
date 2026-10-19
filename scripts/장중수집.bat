@echo off
REM ───────────────────────────────────────────────────────────
REM  장중 수집 (5분 간격) — 작업 스케줄러가 이 파일을 부른다.
REM  스크립트 안에 '평일 08:55~15:40' 이 들어 있어서, 장이 아닐 때 불려도 아무것도 하지 않는다.
REM  기록은 scripts\장중수집.log 에 쌓인다 (깃에는 올라가지 않는다).
REM ───────────────────────────────────────────────────────────
cd /d "%~dp0.."
echo [%date% %time%] >> "%~dpn0.log"
set "PY="
for %%P in ("%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" "%LOCALAPPDATA%\Python\bin\python.exe" "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe") do if not defined PY if exist %%P set "PY=%%~P"
if not defined PY set "PY=python"
"%PY%" app\collect_live.py >> "%~dpn0.log" 2>&1
