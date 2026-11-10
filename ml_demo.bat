@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\ml_demo.ps1" %*
if errorlevel 1 (pause & exit /b 1)
