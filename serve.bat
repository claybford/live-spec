@echo off
rem Double-click to read this living specification in your browser:
rem starts `lspec serve --open` and keeps serving until this window closes or Ctrl-C.
cd /d "%~dp0"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (where py >nul 2>nul && set "PY=py -3")
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python 3 is needed to serve this spec: https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% lspec.py serve --open %*
if errorlevel 1 pause
