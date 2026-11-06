#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null; then
  echo "[드롭컷] Python 3가 필요합니다: https://www.python.org/downloads"; exit 1
fi
if [ ! -f .venv/installed.ok ]; then
  echo "[드롭컷] 처음 실행이라 필요한 프로그램을 설치합니다..."
  [ -x .venv/bin/python ] || python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -r requirements.txt
  echo ok > .venv/installed.ok
fi
echo "[드롭컷] 브라우저에서 http://127.0.0.1:8000 이 열립니다."
exec .venv/bin/python -m dropcut "$@"
