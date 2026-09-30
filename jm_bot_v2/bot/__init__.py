"""JM Bot v2 包 — 独立 OneBot 监听器（由根目录 jm_bot.py 单体重构而来）

模块结构：
- config    配置加载（config.json 集中管理）
- fsutils   文件/磁盘/JSON 工具
- napcat    NapCat OneBot HTTP API（底层）
- roles     角色系统（7 人设 + 口吻转换）
- messaging 消息发送门面（统一注入角色口吻）
- runtime   线程池与阻塞调用包装
- state     共享运行状态（下载去重/进度/冷却）
- jm_client JMComic 客户端与查询域逻辑
- downloader 下载核心（进度/取消/卡死检测/PDF|ZIP）
- ai_chat   AI 聊天（意图分类 → 执行 → 猫娘回复）
- messages  文案库
- handlers  命令处理器（download/browse/chat/misc）
- router    正则路由分发
- runner    WebSocket 主循环
"""
