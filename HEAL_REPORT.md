# TVBox 自愈运行报告

- 运行时间：2026-11-27 08:37:24 +0800
- 本轮动作：**config.json 无变化（健康源与上一版一致）**
- 当前激活点播源：https://byshino.github.io/tvbox-mirror/clean-selfhost.json
- 镜像组选择：clean-selfhost→liu673cn-box
- 当前激活直播源：https://byshino.github.io/tvbox-mirror/live-good.m3u
- 连续失败轮次：0

## 候选源探测明细

| 源 ID | 类型 | 优先级 | HTTP | 延迟ms | 结果 | 数量 | 说明 |
|---|---|---|---|---|---|---|---|
| clean-selfhost | json | 1 | 200 | 37 | 健康 | 200 | OK |
| clean-mirror-v2 | json | 2 | 200 | 35 | 健康 | 210 | OK |
| selfhost-snapshot | json | 3 | 200 | 32 | 健康 | 234 | OK |
| liu673cn-ghpages | json | 3 | 200 | 62 | 健康 | 234 | OK |
| live-good | m3u | 1 | 200 | 28 | 健康 | 714 | OK |

## 机制说明

- VOD 同内容镜像同组去重，每组只取一个；live 不同频道集必须分不同组，否则会丢频道。
- 多重复探测 + 延迟门槛，慢源偶发成功不会误判健康。
- 失效保护按 vod/live 分组独立回填上一版，绝不让电视拉空。
- 原子写入杜绝半截 JSON；连续失效达阈值升级告警。
