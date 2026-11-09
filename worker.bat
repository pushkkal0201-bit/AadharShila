@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\worker.ps1" %*
if errorlevel 1 (pause & exit /b 1)
