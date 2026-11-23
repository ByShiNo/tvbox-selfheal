# TVBox 自愈方案 · 跨对话编队审查报告

> 生成时间：2026-11-23 18:24 CST
> 编队：5 个独立审查 agent（源池可靠性 / 直播源 / 代码稳健性 / 无人值守部署 / 跨session整合）+ 1 个首席整合
> 方法：以 `_audit_evidence.md`（当日真实 HTTP 探测）为唯一事实基线，并行审查后汇总去重

## 联立了两个对话

| 对话 | 产出 | 问题 |
|---|---|---|
| 目标 session `8df822b8...` | 选包指南、APK 传输、App 更新三档、失效源黑名单、参考来源最全 | 含两处被实测推翻的旧内容：`ipv4 目录/ipv4.m3u`（不存在）、`subs:[{name,url}]` 对象数组 |
| 当前工程线 | `heal.py` + failover_group 去重 + 失效保护 + 故障注入 | 直播仅 IPv6、ghproxy 慢源进候选、README 私有仓口径矛盾 |

整合基线：实测证据为准；工程在当前目录增量修补；目标 session 的丰富度吸收进来但逐条纠错。`subs` 的 234×3 去重修正已确认保留。

## 审查发现的不妥（按严重度）

### CRITICAL（4）
1. **点播源同仓单点**：3 个可用入口全是 `liu673cn/box` 一份 m.json 的镜像，该仓停更/被封则全灭；实测无第二家可用公共仓。→ 加自托管快照兜底（`selfhost-snapshot` 占位）。
2. **直播仅 IPv6**：无 IPv6 的宽带/电视逐条必失败；`index.m3u`(IPv4,94)、`itv.m3u`(IPv4,189) 没进候选。→ 已补入并设独立 failover_group。
3. **私有仓 raw 电视拉不到**：README L41「私有即可」与 L57「可能匿名失败」自相矛盾；私有仓 raw 对电视返回 404。→ 明示必须 Public。
4. **公开仓 60 天闲置禁 schedule 无自恢复**：workflow 无法恢复自身，形成死锁。→ 加外部 `watchdog.py`。

### HIGH（6）
- ghproxy 实测 >12s 超时却当稳定 failover（故障注入会切到慢源）→ 已删除，补实测 200 的 ghpages。
- 失效保护用 `and`：点播单独全挂会写出 `subs=[]` 拉空电视 → 已改为分组独立回填。
- 非原子写入，中断留下半截 JSON → 已改 tmp+fsync+os.replace。
- 无 watchdog/心跳 → 已加 watchdog.py。
- README「换成 ipv4 目录/ipv4.m3u」是死路（该文件不存在）→ 已改为真实文件名说明。
- 慢源单次探测误判 → 已改 2 次重复探测 + 延迟门槛 + 站点数基线。

### MEDIUM（已一并修复）
连续失败计数不参与决策（→升级告警）、读失败误判首次覆盖有效配置（→区分处理）、probe_all 无总超时（→deadline）、min_channels=5 过松（→40）、本地缓存兜底缺失、cron 6h 窗口（→3h）、fork 只读 push 失败（→明示不用 fork）、push 失败静默（→显式失败退出）、README 保活理由错、subs 结构口径不一致、失效源黑名单/App三档/选包判据/去重语义缺失（→README 全部补齐）。

### LOW（已一并修复）
state.history 类型校验、pick_failover 自排序、字段名 `max_sources_per_group`→`max_active_sources`、APK 传输与验收、参考来源、6秒/6小时口径区分。

## 实际落地修订

| 文件 | 修订 |
|---|---|
| `candidates.json` | 删 ghproxy；补 ghpages(200 实测) + 自托管快照占位；live 改 3 条(IPv4×2 + IPv6)；min_channels 40；字段名改 max_active_sources；加 failures_before_alert |
| `heal.py` | 重写为 v2 加固版：原子写、单源超时、2次重复+延迟+基线校验、分组独立回填、连续失败告警、读失败区分、总超时兜底、自排序、类型校验 |
| `heal.yml` | cron 6h→3h；push 失败显式失败退出；注明必须 Public/勿 fork |
| `watchdog.py` | 新增：外部心跳检测 + 告警(Bark/Server酱) + workflow 自恢复 |
| `README.md` | 全面重写：Public 要求、60天闲置对策、watchdog 部署、IPv4 直播真实文件名、失效源黑名单、App 三档、选包判据、APK 传输、验收、残留风险 |
| 备份 | 原始版本在 `tvbox-selfheal.bak-20261123/` |

## 验证结果

- 语法检查：`python -m py_compile heal.py watchdog.py` EXIT=0
- 最终实跑：点播 3/3 + 直播 3/3 全健康，config 生成 subs=1 / lives=3
- 故障注入 A（点播单独全挂）：保留上一版 subs，直播不受影响 → **PASS**（v1 此场景会拉空）
- 故障注入 B（全部失效）：保留上一版完整配置 → **PASS**
- 故障注入 C（主源 404）：自动切 CDN → **PASS**

## 补遗（2026-11-23 后续）：CRITICAL-① 点播同仓单点已闭环

编队审查列出的唯一未根除 CRITICAL——点播源全是 liu673cn/box 一个仓的镜像——已用独立仓库 `tvbox-mirror`（工作区 `../tvbox-mirror/`）根除：
- `snapshot.py` 每 6 小时按 main→jsdelivr→ghpages failover 抓 m.json，校验 sites≥10 且不低于基线一半，原子写 + last good 保护；
- `candidates.json` 的 `selfhost-snapshot` 已 `enabled:true`、`priority:4` 同组垫底，url 指向已上线的 `https://github.com/ByShiNo/tvbox-mirror`，只在三个公共入口全挂时被 heal.py 选中；
- 故障注入实测：上游返回 sites=2 的空壳 m.json → 判不合格 → `mirror/m.json` SHA256 前后一致（last good 保留）→ PASS。

**4 个 CRITICAL 现全部闭环**：①同仓单点→tvbox-mirror；②直播 IPv4→已补 index/itv；③私有仓→Public 明示；④60 天闲置→watchdog。

## 结论

当前 v2 方案在「人不在、电脑不在」场景下可自愈：订阅挂→云端 3 小时内切源；workflow 停摆→外部 watchdog 告警+自恢复；点播全挂→保留上一版不拉空；直播无 IPv6 也有 IPv4 可用；上游整仓停更→tvbox-mirror 快照兜底。残余风险仅剩 GitHub 平台依赖（schedule 延迟/闲置禁用已由 watchdog 缓解）与采集站本身，均已在 README 第九节如实说明。
