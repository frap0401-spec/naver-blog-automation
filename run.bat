@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 드롭컷

rem ---- 1. Python 확인 (없으면 자동 설치) ----
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if not defined PY (
  echo [드롭컷] Python이 없어 자동으로 설치합니다. 잠시만 기다려 주세요...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo.
    echo [드롭컷] 자동 설치에 실패했습니다.
    echo https://www.python.org/downloads 에서 직접 설치해 주세요.
    echo 설치 첫 화면에서 "Add python.exe to PATH" 를 꼭 체크하세요.
    start https://www.python.org/downloads
    pause
    exit /b 1
  )
  echo.
  echo [드롭컷] Python 설치 완료! 이 창을 닫고 run.bat 을 한 번 더 실행해 주세요.
  pause
  exit /b 0
)

rem ---- 2. 처음 한 번만 필요한 프로그램 설치 ----
if not exist ".venv\installed.ok" (
  echo [드롭컷] 처음 실행이라 필요한 프로그램을 설치합니다. 2~5분 걸려요...
  if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [드롭컷] 설치 중 오류가 났습니다. 인터넷 연결을 확인하고 다시 실행해 주세요.
    pause
    exit /b 1
  )
  echo ok> ".venv\installed.ok"
)

rem ---- 3. 실행 ----
echo [드롭컷] 브라우저에서 http://127.0.0.1:8000 이 열립니다. 이 검은 창은 닫지 마세요.
".venv\Scripts\python.exe" -m dropcut %*
if errorlevel 1 pause
