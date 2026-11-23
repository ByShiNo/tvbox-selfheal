# 实测证据（2026-11-23 18:13 CST，Windows PowerShell + Python 直连）

供 agent 编队审查方案时引用，所有结论均为实际 HTTP 请求结果，非推测。

## 1. 点播订阅源

| URL | 实测 | 备注 |
|---|---|---|
| https://raw.githubusercontent.com/liu673cn/box/main/m.json | 200, 50584B, 234 sites | 当前主源，可用 |
| https://fastly.jsdelivr.net/gh/liu673cn/box@main/m.json | 200, 50584B | CDN 镜像，可用 |
| https://liu673cn.github.io/box/m.json | 200, 50584B | GitHub Pages 镜像，可用 |
| https://ghproxy.net/https://raw.githubusercontent.com/liu673cn/box/main/m.json | 超时 (>12s) | 代理镜像，实测不稳定 |
| https://raw.githubusercontent.com/leevi0909/TVBox/main/jsm.json | 404 | 已失效（旧方案曾推荐） |
| https://raw.githubusercontent.com/uzshare/uzbox/main/config.json | 404 | 已失效 |
| https://jihulab.com/yingshicang/yingshicang/-/raw/main/yingshicang.json | 401 需登录 | 匿名不可用 |
| https://gitlab.com/yingshicang/yingshicang/-/raw/main/yingshicang.json | 404 | 失效 |
| takagen99/Box, mengtemps/TVBox, xyqyear/TVBox 等多个第三方仓 | 404 | 未找到可用替代维护者 |

**关键结论：所有可用点播源都是 liu673cn/box 这一个仓的镜像（3 条入口）。存在单点依赖——该仓整体停更或被封时，全部镜像同时失效。**

## 2. 直播源（fanmingming/live 仓库真实目录）

API: https://api.github.com/repos/fanmingming/live/contents/tv/m3u 返回的文件：

| 文件 | 大小 | 频道数 | 地址类型 | URL |
|---|---|---|---|---|
| index.m3u | 25855B | 94 | 纯 IPv4 | https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/index.m3u |
| itv.m3u | 44468B | 189 | 纯 IPv4 | https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/itv.m3u |
| demo.m3u | 16890B | 158 | 纯 IPv4 | https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/demo.m3u |
| ipv6.m3u | 22781B | 82 | IPv6 地址 | https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u |

**关键结论：**
1. 不存在 ipv4.m3u 这个文件（旧 README 说"换成 ipv4 目录版本"是错的）。
2. 当前 config.json 只用了 ipv6.m3u。没有 IPv6 的宽带/电视会全部播放失败。
3. 应改用 index.m3u（IPv4，94 频道）作主源，或用 subs 并列 index+itv 双源，ipv6 作为有 IPv6 环境时的可选补充。

## 3. App 版本

- FongMi/Release 最新版 5.9.0（2026-11-22 发布）。
- 官方文档 https://fongmi.github.io/TV/ 确认：App 本身不内置任何内容源，也无内置自更新机制。
- latest 直链可用模式：https://github.com/FongMi/Release/releases/latest/download/leanback-arm64_v8a.apk

## 4. 当前方案实测结果

- heal.py 本地实跑：4/4 源健康（3 点播镜像 + 1 直播），EXIT=0。
- 故障注入1：主源+CDN 改 404 → 自动切 ghproxy 镜像，config.json 的 subs 正确更新，EXIT=0。
- 故障注入2：全部源改 404 → 触发失效保护，保留上一版 config.json，连续失败计数=1，EXIT=0。
- 注意：故障注入1 切到了 ghproxy，但本次实测 ghproxy 超时，说明"优先级排序 + 健康判定"在 ghproxy 这种慢源上可能误判（超时阈值 12s 内偶发成功偶发失败）。

## 5. 两个 session 的关系

- 当前 session：产出 tvbox-selfheal/（heal.py 体系）。
- 目标 session 8df822b8：同一方案的平行版本，包含一条关键技术修正记录——"subs 是并列全部加载语义，三个镜像都写进去会导致 234×3 重复站点 → 改为 failover_group 每组只选一个"。当前方案已吸收该修正。
- 目标 session 提取文件：`_session_8df822b8_final.txt`（助手正文 13 段）、`_session_8df822b8_chat.txt`（用户消息）。
