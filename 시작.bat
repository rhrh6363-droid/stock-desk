@echo off
chcp 65001 > nul
title 특징주 데스크
cd /d "%~dp0"

set PY=C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe
if not exist "%PY%" set PY=python

if "%KRX_ID%"=="" goto nocred
if "%KRX_PW%"=="" goto nocred

echo.
echo  특징주 데스크를 시작합니다. 브라우저가 열립니다.
echo  멈추려면 이 창에서 Ctrl+C 를 누르거나 창을 닫으세요.
echo.
"%PY%" app\server.py
goto end

:nocred
echo.
echo  [중단] KRX 계정이 설정되지 않았습니다.
echo.
echo   새 명령 프롬프트에서 아래 두 줄을 실행한 뒤 이 창을 다시 여세요.
echo.
echo     setx KRX_ID "아이디"
echo     setx KRX_PW "비밀번호"
echo.
pause

:end
