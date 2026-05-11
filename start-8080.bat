@echo off
setlocal
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\start-portable-8080.ps1" -Port 8080
