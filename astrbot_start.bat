@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   AstrBot - JM Comic Plugin
echo ============================================
echo.

:: 杀掉旧进程
echo [1/3] Cleaning old processes...
taskkill /f /im astrbot.exe >nul 2>&1
timeout /t 2 /nobreak >nul

:: 清除锁文件
echo [2/3] Removing lock file...
if exist "%USERPROFILE%\.astrbot\astrbot.lock" del /f "%USERPROFILE%\.astrbot\astrbot.lock"

:: 启动
echo [3/3] Starting AstrBot...
echo.
echo   WebUI: http://localhost:6185
echo   用户:  astrbot
echo   密码:  jm123456
echo.
set PATH=%USERPROFILE%\.local\bin;%PATH%
cd /d "%USERPROFILE%\.astrbot"
astrbot run

pause
