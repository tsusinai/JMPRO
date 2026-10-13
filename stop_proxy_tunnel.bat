@echo off
chcp 65001 >nul
echo 正在停止 JMComic SSH 反向代理隧道...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name = 'ssh.exe'\" | Where-Object { $_.CommandLine -like '*10808:127.0.0.1:7892*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('已终止进程 PID: ' + $_.ProcessId) }"
echo 隧道已停止。云端 JMComic 已自动回退到直连模式。
timeout /t 3 >nul
