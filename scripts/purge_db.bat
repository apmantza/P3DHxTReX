@echo off
setlocal

set DB_PATH=data\processed\bbirr.db

if not exist %DB_PATH% (
  echo DB not found at %DB_PATH%
  exit /b 1
)

del %DB_PATH%
if errorlevel 1 goto :error

echo DB deleted: %DB_PATH%
exit /b 0

:error
echo Failed to delete DB.
exit /b 1
