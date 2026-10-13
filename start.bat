@echo off

chcp 65001

cd /d "%~dp0"



echo ============================================

echo   JM Bot - Full Stack Startup

echo ============================================

echo.



echo [1/3] NapCat...

tasklist 2>nul | findstr /i "NapCatWinBootMain.exe" >nul

if errorlevel 1 (
    if defined NAPCAT_SHELL_DIR (
        start "NapCat" /min /d "%NAPCAT_SHELL_DIR%" "%NAPCAT_SHELL_DIR%\NapCatWinBootMain.exe" %NAPCAT_QQ%
        echo   Waiting 8s...
        timeout /t 8 /nobreak >nul
    ) else (
        echo   [Notice] NAPCAT_SHELL_DIR not set. Please launch NapCat manually.
    )
) else (
    echo   Already running.
)



echo [2/3] GoodbyeDPI...

tasklist 2>nul | findstr /i "goodbyedpi.exe" >nul
if not errorlevel 1 (
    echo   Killing old instances...
    taskkill /f /im goodbyedpi.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
)
cd goodbyedpi
start "GoodbyeDPI" /min goodbyedpi.exe -5
cd ..
timeout /t 3 /nobreak >nul
echo   Started.



echo [3/3] JM Bot...

:: 防止多实例导致双回复
tasklist 2>nul | findstr /i "python.exe" >nul
if not errorlevel 1 (
    echo   Killing old Python...
    taskkill /f /im python.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
)

python jm_bot.py

pause

