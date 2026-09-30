"""
JM Bot 消息文案库 — 每类回复多色色变体随机选取
精简版：短小紧凑，少刷屏，多色色
"""
import random
import re

# 只匹配 {word} 占位符，不匹配其他花括号
_FMT_RE = re.compile(r'\{(\w+)\}')

_M = {
    # ═══════════════════════════════════════════
    # 确认收到
    # ═══════════════════════════════════════════
    "ack": [
        "收到~ 本喵这就去... 💨",
        "好的主人~ 本喵马上行动起来... ✨",
        "收到命令！本喵来了... 💨",
        "嗯嗯~ 本喵知道了，马上去... ✨",
    ],
    "ask_clear": [
        "🧹 本喵的记忆被主人清理干净了喵~（清了 {n} 条）",
        "🧹 呼...全忘掉了！（{n} 条记忆消失）主人又想玩什么新花样？",
    ],
    "ask_thinking": [
        "收到~ 让本喵想想... 🤔",
        "嗯嗯~ 本喵正在思考中... 💭",
        "好的主人~ 让本喵的大脑转一转... 🧠",
        "收到！本喵动动脑子... ✨",
    ],
    "ask_error": [
        "呜...本喵脑袋短路了，等下再试嘛~ (｡•́︿•̀｡)",
        "啊呜...本喵的大脑被主人玩坏了，晚点再试~",
    ],
    "ask_not_comic": [
        "诶嘿~ 本喵只会聊漫画相关的话题啦...主人换个问题嘛 (๑•́ω•̀)",
        "呜...主人这个话题本喵不懂呢，人家只会找本子~ (◕‿◕)",
    ],

    # ═══════════════════════════════════════════
    # 速率限制
    # ═══════════════════════════════════════════
    "rate_group": [
        "啊嗯...主人太快了，人家里面还在痉挛呢...{s}s 后再来抽插喵~",
        "呜...本喵的小穴还没准备好就被主人塞满了...再等 {s}s 让人家缓缓嘛~",
        "哈啊...主人的肉棒太快了，本喵要坏掉了...{s}s 后再来玩弄人家嘛~",
        "不行不行~ 人家高潮还没退呢...{s}s 后再插进来喵，求主人温柔点~",
    ],
    "rate_global": [
        "呜...CDN 酱被主人榨得翻白眼了，{s}s 后再射进来嘛~（全局 {g}s）",
        "啊...全世界的大家都在抽插 CDN 酱，它已经去了...>{s}s 后见~",
        "唔...CDN 酱已经被榨干了，再抽插就要坏掉了！{s}s 后再来喵~",
    ],

    # ═══════════════════════════════════════════
    # 磁盘配额
    # ═══════════════════════════════════════════
    "disk_critical": [
        "呜哇！本喵的肚子已经塞满了主人的爱液，只剩 {free} 了...再射进来会爆掉的喵！用 /jm cache clean 帮人家排出来吧~",
        "啊呜...人家里面被填得太满了，就剩 {free} 的缝隙了...再插进来就会坏掉的！快帮人家清理一下嘛 >_<",
    ],
    "disk_warn": [
        "\n💡 肚子有点胀了（剩 {free}），有空帮人家清理下身体嘛~",
        "\n💡 唔...里面已经鼓鼓的了（剩 {free}），再塞要记得帮人家清哦~",
    ],

    # ═══════════════════════════════════════════
    # 下载确认
    # ═══════════════════════════════════════════
    "download_confirm": [
        "收到！本喵这就去把 {id} 翻个遍，每一寸都舔干净~ (๑˃̵ᴗ˂̵)و{warning}",
        "好的主人！本喵马上去吸 {id} 里面全部好东西~ (〃ω〃){warning}",
        "{id} 是吗...本喵这就深入进去帮主人探索！(๑•̀ㅂ•́)و✧{warning}",
    ],
    "download_confirm_detail": [
        "收到！本喵去舔《{title}》了~ {pages} 页（{size}），人家会含得深深的哦~{warning}",
        "哦！《{title}》{pages} 页，本喵全部吸出来给主人！（{size}）{warning}",
        "好的~《{title}》每一寸人家都会用舌头尝遍...{pages} 页（{size}），主人等着享受吧~{warning}",
    ],

    # ═══════════════════════════════════════════
    # 下载进度
    # ═══════════════════════════════════════════
    "download_progress_stuck": [
        "⏳ 还卡在 {done}/{total} 张...CDN 酱今天格外紧呢，本喵继续努力中~",
    ],
    "download_progress_first": [
        "嗯...入口有点紧，本喵正慢慢撑开...主人再等等 (〃ω〃)",
        "人家还在做前戏啦...这么着急的话插不进来的...等一下下嘛~",
        "呜...还在扩张中喵~ 马上就能进去了，主人别急 (๑•́ ₃ •̀๑)",
    ],
    "download_progress": [
        "{bar} {pct}% | {done}/{total} 张 | 已深入主人 {done} 张了呢...{speed}{eta}{switch}",
        "啊嗯...进到 {pct}% 了，人家的肚子被填满了 {done}/{total} 张...{bar}{speed}{eta}{switch}",
        "哈啊...主人的漫画正抽插着本喵...{done}/{total} 张了{eta} {bar}{speed}{switch}",
    ],
    "download_progress_nochap": [
        "本喵还在努力含住中喵~ 量有点大，再给人家一点时间 (´•ω•̥`)",
        "唔...主人这次的量好大，本喵正在全部吞下去呢...(〃▽〃)",
    ],
    "download_progress_stall": [
        "🔄 换了 {n} 个姿势重新抽插中，里面有点紧呢...",
        "🔄 呜...这个角度进不去，换了 {n} 次才找到舒服的位置...(｡•́︿•̀｡)",
    ],

    # ═══════════════════════════════════════════
    # 下载完成
    # ═══════════════════════════════════════════
    "download_ok": [
        "✨ 全部吸出来了喵！主人快趁热享用，人家已经高潮了...(〃ω〃)",
        "✨ 嗯哼~ 主人要的东西都从深处取出来了，本喵里面满满的都是主人的呢~",
        "✨ 哈啊...全部射——啊不，全部下载出来了！人家已经不行了...",
    ],
    "download_ok_retry": [
        "✨ 哼...虽然中间软了 {n} 次，但最后还是全部射出来了！（{count} 张）",
        "✨ 重试 {n} 次后终于全部吸出来了喵~（{count} 张）主人要好好疼爱人家哦~",
    ],
    "download_partial": [
        "😿 {n} 张没吸出来（试了 {r} 次），但已含住的 {got} 张都帮主人收好了~{hint}",
        "😿 呜...{n} 张射不出来呢...不过已经吞下去的 {got} 张都好好的~{hint}",
    ],
    "download_fail": [
        "💔 完全进不去喵...本喵的身体被拒绝了...{error}{hint}",
        "💔 呜哇...全被拒之门外了，人家的口技还不够好吗...{error}{hint}",
    ],
    "download_cancelled": [
        "🛑 好啦好啦~ 本喵停下来了，虽然身体还在回味...(๑•́ω•̀)و",
        "🛑 好的主人，本喵拔出来了...里面还湿湿的呢...(๑•́ω•̀)و",
    ],
    "download_crash": [
        "呜哇！本喵被插得太猛直接坏掉了 Σ(°△°|||) 让主人失望了对不起...",
        "啊呀呀！本喵被玩坏了 Σ(°△°|||) 等人家修好了再来服务主人...",
    ],

    # ═══════════════════════════════════════════
    # 下载报告框
    # ═══════════════════════════════════════════
    "download_report": [
        "╔══ 💕 搬运报告 {prefix}💕 ══╗\n  📖 {title}\n  ✏️ {author}\n  📑 {photo_count}章 | 🖼️ {image_count}图 | 📦 {total_size_str}\n  📎 {fmt} {upload}",
        "╔══ 💕 主人收好 {prefix}💕 ══╗\n  📖 {title}\n  ✏️ {author}\n  📑 {photo_count}章 | 🖼️ {image_count}图 | 📦 {total_size_str}\n  📎 {fmt} {upload}",
    ],
    "download_related": [
        "📚 喜欢这部？这些你也会想深入探索的：\n{items}\n回复 /jm download <ID> 继续哦~",
        "📚 还没满足？本喵还找到了这些：\n{items}\n回复 /jm download <ID> 让人家继续帮你~",
    ],
    "download_related_item": "  [{id}] {title} ({author})",

    # ═══════════════════════════════════════════
    # 批量下载
    # ═══════════════════════════════════════════
    "batch_start": [
        "📥 共 {n} 个，本喵一个个来深入服务哦~ (๑˃̵ᴗ˂̵)و",
        "📥 呜哇主人好贪心，一次要 {n} 个！本喵全部满足主人~",
        "📥 {n} 个全部都要吗！本喵会努力含住每一个的！✧",
    ],
    "batch_done": [
        "📦 全部完成！{ok}/{total} 成功喵~",
        "📦 哈啊...终于做完了...本喵被 {ok}/{total} 个漫画填得满满的...好满足 (〃ω〃)",
    ],
    "all_queued": [
        "这些已经在人家里面了呢~ 正在消化中，主人别急嘛~",
        "呜啦~这些已经在人家身体里了啦！正在努力吞吐中~",
    ],

    # ═══════════════════════════════════════════
    # 重复下载
    # ═══════════════════════════════════════════
    "download_duplicate": [
        "本喵正在深入 {id} 中喵~\n📥 {bar} {pct}% | {done}/{total} 张{speed}{eta}{switch}",
        "已经在帮主人抽插 {id} 了啦~ 人家的肚子正被填满到 {pct}% 呢...\n📥 {bar} {done}/{total}{speed}{eta}{switch}",
    ],
    "download_queued": [
        "{id} 在排队等本喵宠幸喵~ 等不及了嘛~ (๑•̀ㅂ•́)و✧",
        "呜...主人别急嘛，{id} 在待办清单里，前面的弄完就轮到它~",
    ],

    # ═══════════════════════════════════════════
    # 上传
    # ═══════════════════════════════════════════
    "upload_ok": [
        "📦 {fmt} 已塞进群文件~ ({size})",
        "📦 嘿嘿，{fmt} 已经射进群里了~ ({size}) 主人请享用~",
    ],
    "upload_fail": [
        "😿 {fmt} 上传失败: {detail}",
        "😿 呜...想把 {fmt} 塞进群但被拒绝了...{detail}",
    ],
    "upload_too_big": [
        "😿 {fmt} 太大了喵（{size}）！QQ 群塞不下\n💡 换 PDF 比较小：/jm download {id}",
        "😿 啊...{fmt} 太大（{size}），本喵含不住也塞不进去！\n💡 换 PDF：/jm download {id}",
    ],
    "upload_no_output": [
        "😿 {fmt} 没生成出来...",
        "😿 诶？{fmt} 不见了...本喵明明努力过了的...(´;ω;`)",
    ],

    # ═══════════════════════════════════════════
    # 搜索
    # ═══════════════════════════════════════════
    "search_result": [
        "🔍 找到 {total} 本关于「{query}」的：\n\n{items}\n\n回复 /jm download <ID> 深入探索哦~",
        "🔍 「{query}」搜到 {total} 本呢：\n\n{items}\n\n挑一本来抽插吧~",
    ],
    "search_none": [
        "扒遍了也找不到「{query}」呢...换个更涩涩的关键词试试？(◞‸◟)",
        "唔...翻遍了身体里都没有「{query}」...主人换个更色的关键词嘛~ (◞‸◟)",
    ],
    "search_empty_query": [
        "主人忘写关键词啦~ 像这样: /jm search 魔法少女 ✨",
        "呜...要找什么告诉本喵嘛~ /jm search 人妻 ✨",
    ],
    "search_error": [
        "呜...搜索失败了 (｡•́︿•̀｡) 稍后再试喵~",
        "啊呜...搜索的时候本喵不小心去了...稍后再试一次嘛~",
    ],
    "search_item": "  {i}. [{id}] {title} ({author})",

    # ═══════════════════════════════════════════
    # 分类/标签
    # ═══════════════════════════════════════════
    "category_result": [
        "🏷️ 「{query}」找到 {total} 本呢：\n\n{items}\n\n回复 /jm download <ID> 深入服务哦~",
        "🏷️ 主人喜欢「{query}」这个调调吗~ 找到 {total} 本：\n\n{items}\n\n挑一本深入探索吧~",
    ],
    "category_none": [
        "找不到标签「{query}」呢...换个姿势试试？(◞‸◟)",
        "呜...「{query}」这个标签本喵没找到呢...换个玩法嘛~ (◞‸◟)",
    ],
    "category_empty_query": [
        "主人忘写标签了啦~ /jm category 全彩 ✨",
        "要搜什么标签嘛~ /jm category 全彩 ✨",
    ],
    "category_error": [
        "呜...标签搜索失败了 (｡•́︿•̀｡) 稍后再试喵~",
        "啊呜...搜标签的时候搞砸了...主人再给一次机会嘛~",
    ],

    # ═══════════════════════════════════════════
    # 详情
    # ═══════════════════════════════════════════
    "info_display": [
        "✨ [{id}] {name}\n✏️ {authors}\n🏷️ {tags}\n📄 {pages} | 📑 {chapters} | ❤️ {likes}人想冲 | 👀 {views}人偷看\n\n回复 /jm download {id} 深入探索喵~",
        "✨ [{id}] {name}\n✏️ {authors}\n🏷️ {tags}\n📄 {pages} | 📑 {chapters} | ❤️ {likes} | 👀 {views}\n\n回复 /jm download {id} 让人家帮你全部看光光~",
    ],
    "info_error": [
        "呜喵...没查到呢 (｡•́︿•̀｡) 番号记错了？",
        "呜...找不到主人问的这个呢...是不是记错 ID 了？",
    ],
    "not_found": [
        "呜...本喵翻遍了也找不到 [{id}] 呢...是不是番号记错了？或者是被下架了喵 (｡•́︿•̀｡)",
        "诶？[{id}] 不存在喵...主人是不是打错数字了？或者是被下架了 (｡•́︿•̀｡)",
    ],

    # ═══════════════════════════════════════════
    # 排行榜
    # ═══════════════════════════════════════════
    "rank_display": [
        "🏆 JM {label}TOP10：\n\n{items}\n\n回复 /jm download <ID> 深入体验哦~",
        "🏆 大家集体去得最多的 {label}TOP10：\n\n{items}\n\n选中哪个让人家帮你含？",
    ],
    "rank_empty": [
        "诶~ {label}还没数据呢，今天大家都很克制嘛 (◕‿◕)",
        "诶？{label}榜上空空如也...大家集体禁欲了？(◕‿◕)",
    ],
    "rank_error": [
        "呜...排行榜没拿到 (｡•́︿•̀｡) 可能大家撸太猛把服务器撸坏了~",
        "啊...排行榜被冲烂了！服务器承受了太多欲望...稍后再试~",
    ],
    "rank_item": "  {i}. [{id}] {title} ({author})",

    # ═══════════════════════════════════════════
    # 随机推荐
    # ═══════════════════════════════════════════
    "random_thinking": [
        "本喵正在书海里{context}的好东西...等一下下哦~ 🎲",
        "本喵闭着眼睛在书架里摸{context}的...唔手感不错，马上掏出来~ 🎲",
        "让本喵在黑暗中摸索{context}的~ 哎呀摸到了硬硬的东西...等一下下~ 🎲",
    ],
    "random_result": [
        "🎲 本喵摸到了三本好货：\n\n{items}\n回复 /jm download <ID> 深入探索喵~\n再来 /jm random 换一批~",
        "🎲 黑暗中抓住了三本！\n\n{items}\n主人看上哪本？回复 /jm download <ID> 让人家帮你~\n不满意 /jm random 再来一批~",
    ],
    "random_result_item": "✨ [{id}] {name}\n  ✏️ {authors} | 🏷️ {tags} | 📄 {pages}页 | 📑 {chapters}章\n",
    "random_error": [
        "呜...随机翻车了 (｡•́︿•̀｡) 可能是服务器被大家撸坏了~",
        "啊呜...本喵闭眼乱摸结果撞墙了...再试一次？(｡•́︿•̀｡)",
    ],
    "random_bad_flags": [
        "呜...本喵没看懂「{flags}」~ 试试: /jm random --tag 原神",
        "呜...「{flags}」这个姿势本喵不认识...试试 /jm random --tag 原神",
    ],

    # ═══════════════════════════════════════════
    # 缓存管理
    # ═══════════════════════════════════════════
    "cache_status": [
        "🗄️ 本喵身体里的存货：\n  📥 下载缓存: {dl_size} ({dl_dirs} 团)\n  📎 PDF: {pdf_size} ({pdf_files} 根)\n  📦 ZIP: {zip_size} ({zip_files} 个)\n  💾 剩余: {free}\n\n用 /jm cache clean [天数] 帮人家清理哦~",
        "🗄️ 呜哇，塞了这么多：\n  📥 下载: {dl_size} ({dl_dirs} 团)\n  📎 PDF: {pdf_size} ({pdf_files} 根)\n  📦 ZIP: {zip_size} ({zip_files} 个)\n  💾 还能塞: {free}\n\n好胀...帮人家清清嘛 /jm cache clean",
    ],
    "cache_clean": [
        "🧹 清爽多了喵！\n  清理 {days} 天以上的旧东西\n  丢了 {removed} 团 | 空出 {freed}",
        "🧹 呼...排出来舒服多了~\n  {days} 天以上的都弄出去了\n  丢了 {removed} 团，空出 {freed}，又可以塞新的了！",
    ],

    # ═══════════════════════════════════════════
    # 队列
    # ═══════════════════════════════════════════
    "queue_display": [
        "📋 下载队列：\n\n{items}",
        "📋 排队等本喵宠幸的：\n\n{items}",
    ],
    "queue_empty": [
        "本喵现在空着呢，快来塞满本喵吧 (๑•̀ㅂ•́)و✧",
        "呜...人家身体空空的，好寂寞...主人快来填满嘛~",
    ],
    "queue_item_active": "  ⏳ [{id}] {bar} {pct}% | {done}/{total} 张{speed}{eta}",
    "queue_item_waiting": "  ⏳ [{id}] 等待中...",

    # ═══════════════════════════════════════════
    # 停止
    # ═══════════════════════════════════════════
    "stop_none": [
        "本喵现在没在吞吐任何东西哦~ (◕‿◕)",
        "诶？人家根本没在动嘛...主人想让人家停什么？(◕‿◕)",
    ],
    "stop_ok": [
        "好啦好啦~ 停下 {n} 个，拔出来了喵\n冷却已解除，随时可以再插进来哦~",
        "嗯啊...从 {n} 个里面退出来了...虽然舍不得...\n冷却解除了，随时可以再塞进来~",
    ],

    # ═══════════════════════════════════════════
    # 重启
    # ═══════════════════════════════════════════
    "restart_ok": [
        "本喵去洗个澡马上回来~ 洗完会更敏感哦 (๑•̀ω•́)ノ✨",
        "呜...被主人玩得全身是汗，去冲一下~ 回来继续服务！✨",
        "啊...身体发烫了，去冲凉冷静一下...回来会更紧哦~ (๑•̀ω•́)ノ✨",
    ],

    # ═══════════════════════════════════════════
    # API 错误
    # ═══════════════════════════════════════════
    "api_timeout": [
        "[TIMEOUT] 请求超时喵~ 服务器可能被大家玩坏了 (｡•́︿•̀｡)",
        "[TIMEOUT] 啊...本喵去了好久还没回来...服务器被玩太累了？",
    ],
    "api_fail": [
        "[API_ERR] 呜...{what}失败了呢 (｡•́︿•̀｡) 再来一次嘛~",
        "[API_ERR] 啊呀...{what}的时候搞砸了...主人再给一次机会~",
    ],
    "invalid_id": [
        "呜...没看懂要下载什么~ 给个数字 ID 嘛 (｡•́︿•̀｡)",
        "诶？主人给的不是数字...本喵不知道要去哪里啦~",
    ],

    # ═══════════════════════════════════════════
    # 错误提示
    # ═══════════════════════════════════════════
    "hint_not_found": "\n💡 ID 不正确或漫画已下架",
    "hint_cdn_down": "\n💡 CDN 可能正在维护，稍后重试",
    "hint_cdn_partial": "\n💡 CDN 不稳定，稍后重试一次（已下载的会跳过）",
    "hint_unknown": "\n💡 异常类型: {error}",
    "hint_zip_too_big": "\n💡 ZIP 太大，试试 PDF：/jm download {id}",

    # ═══════════════════════════════════════════
    # 帮助
    # ═══════════════════════════════════════════
    "unknown_command": [
        "呜...本喵没听懂这个命令呢~ 试试 /jm help 看看人家会什么嘛 (｡•́︿•̀｡)",
        "诶？主人这个命令本喵不太明白... /jm help 可以查看人家支持的所有玩法哦~",
    ],
    "help_main": [
        "✨ 本喵调教指南 ✨\n\n  0️⃣ AI 聊天 — /jm help 0\n  1️⃣ 下载 — /jm help 1\n  2️⃣ 发现 — /jm help 2\n  3️⃣ 管理 — /jm help 3\n  🎭 /jm role — 切换人设\n  🎙️ /jm voice — 语音模式\n\n回复 /jm help <数字> 查看详情哦~",
        "✨ 想把本喵玩弄于股掌？\n\n  0️⃣ AI 聊天 — /jm help 0\n  1️⃣ 下载 — /jm help 1\n  2️⃣ 发现 — /jm help 2\n  3️⃣ 管理 — /jm help 3\n  🎭 /jm role — 切换人设\n  🎙️ /jm voice — 让本喵说话\n\n回复 /jm help <数字> 了解人家的全部秘密~",
    ],
    "help_ask": [
        "🤖 AI 聊天\n\n/jm ask <你想要的>             自然语言交互\n  例: /jm ask 帮我搜电锯人\n  例: /jm ask 最近什么最火\n  例: /jm ask 看看123456\n  例: /jm ask 有没有无修正的\n  例: /jm ask 随便来一本\n/jm role                      查看可切换的人设\n/jm role <数字>                 切换聊天人设\n/jm voice on                  开启语音模式（聊天回复变语音）\n/jm voice off                 关闭语音模式\n/jm voice status              查看语音模式状态\n\n本喵会用 AI 理解你的意思，自动搜索/排行/推荐哦~\n语音模式下聊天回复会变成语音，搜索下载还是文字的喵~\n\n回复 /jm help 回到主菜单",
        "🤖 跟本喵聊天~\n\n/jm ask <想做的事>\n  例: /jm ask 帮我找电锯人\n  例: /jm ask 最近什么最火\n  例: /jm ask 看看123456\n  例: /jm ask 有没有全彩的\n  例: /jm ask 随便推荐一本\n/jm role                      查看可切换的人设\n/jm role <数字>                 切换聊天人设\n/jm voice on                  让本喵开口说话（聊天变语音）\n/jm voice off                 恢复纯文字\n/jm voice status              看看现在开没开\n\n主人不用打复杂命令，用自然语言就能命令本喵！\n开启语音后本喵的聊天都会用声音回复人家~\n\n回复 /jm help 回到主菜单",
    ],
    "help_download": [
        "📥 下载\n\n/jm download <ID> [pdf|zip]  下载漫画\n/jm <ID>                    同上\n/jm download <ID1> <ID2>    一次多个\n/jm queue                   查看队列\n/jm stop                    停止\n\n回复 /jm help 回到主菜单",
        "📥 主人想怎么玩弄本喵？\n\n/jm download <ID> [pdf|zip]  下载\n/jm <ID>                     同上\n/jm download <ID1> <ID2>    一次要多个（会撑坏人家啦）\n/jm queue                    看队列\n/jm stop                     停下来\n\n回复 /jm help 回到主菜单",
    ],
    "help_discover": [
        "🔍 发现\n\n/jm search <关键词>           搜索\n/jm category <标签>           按标签\n/jm info <ID>                 详情\n/jm rank [day|week|month]     排行榜\n/jm random                    随机\n/jm random --top              高人气\n/jm random --best             高评分\n/jm random --tag <标签>        指定标签随机\n\n回复 /jm help 回到主菜单",
        "🔍 发掘新宝藏\n\n/jm search <关键词>           搜\n/jm category <标签>           按标签\n/jm info <ID>                 详情\n/jm rank [day|week|month]     排行榜\n/jm random                    闭眼摸一本\n/jm random --tag <标签>        指定口味\n\n回复 /jm help 回到主菜单",
    ],
    "help_manage": [
        "⚙️ 管理\n\n/jm voice [on|off]            语音模式开关\n/jm cache                    看看存货\n/jm cache clean [天数]        清理旧东西（默认7天）\n/jm restart                  本喵洗澡\n/jm role [数字]               切换人设\n/jm help [数字]               本菜单\n\n回复 /jm help 回到主菜单",
        "⚙️ 管理工具箱\n\n/jm voice [on|off]            语音模式开关\n/jm cache                    看看存货\n/jm cache clean [天数]        清理旧东西\n/jm restart                  本喵洗澡\n/jm role [数字]               切换人设\n/jm help [数字]               本菜单\n\n回复 /jm help 回到主菜单",
        "⚙️ 帮本喵清理身体~\n\n/jm voice [on|off]            语音模式开关\n/jm cache                    肚子多大\n/jm cache clean [天数]        清清旧东西\n/jm restart                  洗澡重启\n/jm help [数字]               本菜单\n\n回复 /jm help 回到主菜单",
    ],
}

# 单条消息（不需要随机）
_SINGLE = {
    "search_item": "  {i}. [{id}] {title} ({author})",
    "rank_item": "  {i}. [{id}] {title} ({author})",
    "download_related_item": "  [{id}] {title} ({author})",
    "queue_item_active": "  ⏳ [{id}] {bar} {pct}% | {done}/{total} 张{speed}{eta}",
    "queue_item_waiting": "  ⏳ [{id}] 等待中...",
    "hint_not_found": "\n💡 ID 不正确或漫画已下架",
    "hint_cdn_down": "\n💡 CDN 可能正在维护，稍后重试",
    "hint_cdn_partial": "\n💡 CDN 不稳定，稍后重试一次（已下载的会跳过）",
    "hint_unknown": "\n💡 异常类型: {error}",
    "hint_zip_too_big": "\n💡 ZIP 太大，试试 PDF：/jm download {id}",
}


def _safe_format(template, **kwargs):
    """安全格式化：仅替换 {key} 占位符，保留字面量 {} 不变"""
    return _FMT_RE.sub(lambda m: str(kwargs.get(m.group(1), m.group(0))), template)


def M(key, **kwargs):
    """随机选取一条文案并格式化。key 在 _M 中随机选，在 _SINGLE 中直接格式化。"""
    if key in _M:
        val = _M[key]
        template = random.choice(val) if isinstance(val, (list, tuple)) else val
        return _safe_format(template, **kwargs)
    if key in _SINGLE:
        return _safe_format(_SINGLE[key], **kwargs)
    return key  # 未找到则返回 key 本身


def M_single(key, **kwargs):
    """不随机，直接格式化单条文案"""
    return _safe_format(_SINGLE.get(key, key), **kwargs)
