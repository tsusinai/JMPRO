@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   JM Comic QQ 官方机器人启动脚本
echo ============================================
echo.

:: 检查是否存在 config.yaml
if not exist "config.yaml" (
    if exist "config.example.yaml" (
        echo [提示] 未检测到 config.yaml，正在从 config.example.yaml 复制模板...
        copy config.example.yaml config.yaml >nul
        echo [提示] 请打开 config.yaml 填入您的 appid 和 secret 后重新运行。
        echo.
        pause
        exit /b 0
    )
)

:: 启动机器人
python -m qq_official_bot.main

pause
