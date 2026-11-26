# TVBox 自愈运行报告

- 运行时间：2026-11-26 08:23:47 +0800
- 本轮动作：**config.json 无变化（健康源与上一版一致）**
- 当前激活点播源：https://fastly.jsdelivr.net/gh/ByShiNo/tvbox-mirror@main/mirror/clean-m-v3.json
- 镜像组选择：clean-mirror-v3→liu673cn-box
- 当前激活直播源：https://fastly.jsdelivr.net/gh/fanmingming/live@main/tv/m3u/index.m3u, https://fastly.jsdelivr.net/gh/fanmingming/live@main/tv/m3u/itv.m3u, https://fastly.jsdelivr.net/gh/fanmingming/live@main/tv/m3u/ipv6.m3u
- 连续失败轮次：0

## 候选源探测明细

| 源 ID | 类型 | 优先级 | HTTP | 延迟ms | 结果 | 数量 | 说明 |
|---|---|---|---|---|---|---|---|
| clean-mirror-v3 | json | 1 | 200 | 188 | 健康 | 210 | OK |
| selfhost-snapshot | json | 3 | 200 | 48 | 健康 | 234 | OK |
| liu673cn-ghpages | json | 3 | 200 | 136 | 健康 | 234 | OK |
| clean-mirror-v2 | json | 2 | 0 | 1862 | 失效 | 0 | URLError: <urlopen error _ssl.c:1001: The handshake operation timed out> (成功 1/2) |
| fanmingming-index | m3u | 1 | 200 | 42 | 健康 | 94 | OK |
| fanmingming-itv | m3u | 2 | 200 | 339 | 健康 | 189 | OK |
| fanmingming-ipv6 | m3u | 3 | 200 | 43 | 健康 | 82 | OK |

## 机制说明

- VOD 同内容镜像同组去重，每组只取一个；live 不同频道集必须分不同组，否则会丢频道。
- 多重复探测 + 延迟门槛，慢源偶发成功不会误判健康。
- 失效保护按 vod/live 分组独立回填上一版，绝不让电视拉空。
- 原子写入杜绝半截 JSON；连续失效达阈值升级告警。
