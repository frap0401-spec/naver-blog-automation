@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 드롭컷

rem ===== 1. Python 찾기 =====
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto have_python
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto have_python

echo [드롭컷] Python이 없어 자동으로 설치합니다. 잠시만 기다려 주세요...
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto python_fail
echo.
echo [드롭컷] Python 설치 완료. 이 창을 닫고 run.bat 을 한 번 더 실행해 주세요.
pause
exit /b 0

:python_fail
echo.
echo [드롭컷] Python 자동 설치에 실패했습니다.
echo https://www.python.org/downloads 에서 직접 설치해 주세요.
echo 설치 첫 화면에서 Add python.exe to PATH 를 꼭 체크하세요.
start "" https://www.python.org/downloads
pause
exit /b 1

:have_python
rem ===== 2. 필요한 프로그램 설치 - 처음 한 번, 또는 목록이 바뀌었을 때 =====
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
if not exist ".venv\Scripts\python.exe" goto venv_fail
fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if not errorlevel 1 goto run_app

echo [드롭컷] 필요한 프로그램을 설치합니다. 처음에는 몇 분 걸려요...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto pip_fail
copy /y requirements.txt ".venv\requirements.installed" >nul

:run_app
rem ===== 3. 실행 =====
echo.
echo [드롭컷] 브라우저에서 http://127.0.0.1:8000 이 열립니다. 이 검은 창은 닫지 마세요.
".venv\Scripts\python.exe" -m dropcut %*
echo.
echo [드롭컷] 프로그램이 멈췄습니다. 위 내용을 캡처해서 보내 주세요.
pause
exit /b 1

:venv_fail
echo [드롭컷] 가상환경을 만들지 못했습니다. Python을 다시 설치해 주세요.
pause
exit /b 1

:pip_fail
echo.
echo [드롭컷] 설치 중 오류가 났습니다. 인터넷 연결을 확인하고 다시 실행해 주세요.
echo 계속 안 되면 위 내용을 캡처해서 보내 주세요.
pause
exit /b 1
