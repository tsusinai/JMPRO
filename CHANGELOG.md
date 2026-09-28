# JM Bot 更新日志

## 2026-06-29

### 下载超时保护
- **首图超时**：5 分钟无任何图片下载 → 自动判定失败，提示 "CDN 不可达"（`download.py:FIRST_IMAGE_TIMEOUT=300`）
- **停滞提醒**：进度连续 140s 无变化 → 发送停滞通知，避免用户长时间无反馈

### 下载队列 Bug 修复（8 项）
- `download_duplicate` NameError 导致重复下载静默崩溃 → 变量名修复
- `_stderr_lock` 全局锁串行化下载 → per-call StringIO 捕获，真并发
- `cmd_stop` 清空队列后线程仍在跑 → 仅标记 `_stop_requests`，清理交 finally
- `finally` 过早丢弃 `_stop_requests` → 增加 5s 冷却期
- `_do_info` 异常致下载崩溃 → 独立 try/except
- `cmd_stop` 不重置全局冷却 → `_last_download_global = 0`
- ETA 硬编码 300KB 回退 → 无数据时不显示
- 进度通知 `image_total==0` 显示 0/0 → 显示"准备中"

### 随机推荐优化
- 跳过 `get_album_detail`（3 次 × 5-8s → 0 次），速度提升 ~30s
- 单页取 3 条，2 次 API 调用

### 网络/CDN
- GoodbyeDPI `-5` 模式确认可用（`-6` 黑名单模式在 Win11 无效）
- `option.yml` 手动固定 API 域名 `[www.cdnhjk.net, www.cdnplaystation6.cc]`
- Cloudflare One 无隧道策略，不可用于翻墙
- `start.bat` 固定 GoodbyeDPI `-5` 模式，移除 WARP 选项

### 新增命令
- `/jm ask clear` — 清理当前群 AI 聊天上下文

### 双回复修复
- ask download：`cmd_ask` 发确认后 return，`cmd_download` 统一回复
- ask clear：用 `send_group_msg` 替代 `send_group_reply`
- 多实例防护：`start.bat` 启动前 `taskkill /f /im python.exe`

### CLI 改进
- `start.bat`：进程检测从 `tasklist /fi` 改为 `tasklist | findstr`（修复误判）
