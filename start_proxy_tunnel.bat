@echo off
chcp 65001 >nul
title JMComic SSH 代理反向隧道 (本机 -> 阿里云)

echo ======================================================
echo    JMComic 本机网络加速隧道启动中...
echo    本地代理端口: 127.0.0.1:7892
echo    服务器映射端口: 127.0.0.1:10808
echo    目标主机: jmbot
echo ======================================================
echo.
echo 提示：
echo 1. 隧道保持开启时，云端 JMComic 会自动走本机网络加速；
echo 2. 关闭此窗口时，云端会自动无缝降级为原生直连；
echo 3. 支持断线自动重试。
echo.

:loop
echo [%date% %time%] 正在连接 SSH 反向代理隧道...
ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -N -R 10808:127.0.0.1:7892 jmbot

echo [%date% %time%] 隧道连接断开，5 秒后尝试重连...
timeout /t 5 >nul
goto loop
