@echo off
echo === JMComic 代理 + SSH 隧道 ===
echo.
echo 保持本窗口运行，关闭则 JM 功能不可用
echo.

start "JM Proxy" pythonw "%~dp0jm_proxy.py"
timeout /t 2 /nobreak >nul

echo 建立 SSH 反向隧道到服务器...
ssh -o "ServerAliveInterval=30" -o "ExitOnForwardFailure=yes" -R 8888:127.0.0.1:8888 -N jmbot

echo 隧道已断开。按任意键退出...
pause >nul
