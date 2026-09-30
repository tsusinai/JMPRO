@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   JM Bot v2 - Windows Startup
echo ============================================
echo.
echo 请确认 NapCat 已启动并完成 QQ 登录。
echo 如需 GoodbyeDPI，请先手动启动并确认网络可用。
echo.
if not exist "config.json" (
  echo [ERROR] 未找到 config.json，请复制 config.example.json 后填写配置。
  pause
  exit /b 1
)
set "PYTHON_EXE=%PYTHON_EXE%"
if "%PYTHON_EXE%"=="" set "PYTHON_EXE=python"
"%PYTHON_EXE%" main.py
pause
