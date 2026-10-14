@echo off
rem Refresh the Bloomberg data of the P3DH database. Use: refresh_bloomberg.bat daily | weekly | monthly
rem The Bloomberg terminal must run and be logged in. The log is data\runs\bbg\refresh_<level>.log.
setlocal
set LEVEL=%1
if "%LEVEL%"=="" set LEVEL=daily
set ROOT=%~dp0..
if not exist "%ROOT%\data\runs\bbg" mkdir "%ROOT%\data\runs\bbg"
cd /d "%ROOT%"
"C:\Users\E40889\Documents\blauto\.venv\Scripts\python.exe" -u scripts\refresh_bloomberg.py %LEVEL% >> "data\runs\bbg\refresh_%LEVEL%.log" 2>&1
exit /b %ERRORLEVEL%
