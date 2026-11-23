# TVBox / 影视TV 自愈系统 v2（agent 编队整合版）

> 目标：电视端只配置一次，之后订阅失效、源挂掉、线路切换、故障告警全部自动完成，你人不在、电脑不在也能自愈。
>
> 本版由 5 个审查 agent（源池/直播/代码/部署/跨session整合）并行审查 + 实测证据修订，副本在 `tvbox-selfheal.bak-20261123/`。

## 一、联立结论：两个对话怎么合一

- **目标对话**（session `8df822b8...`）：内容最全（选包指南、APK 传输、App 更新三档、失效源黑名单、参考来源），但有两处被实测推翻的旧内容：`ipv4 目录/ipv4.m3u`（不存在）、`subs:[{name,url}]` 对象数组。
- **当前工程线**：落地了 `heal.py` + `failover_group` 去重 + 失效保护 + 故障注入，但配置层有三个确定性缺陷：直播只有 IPv6、ghproxy 慢源进候选、README 私有仓口径矛盾。
- **整合基线**：以 `_audit_evidence.md`（2026-11-23 真实 HTTP 探测）为唯一事实基线；工程上在当前 `tvbox-selfheal` 增量修补，不推倒重写。
- **已吸收的关键修正**：`subs` 并列加载会导致 234×3 重复站点 → 改为 `failover_group` 每组只选一个（v1 已吸收，v2 保留）。但**直播不同频道集必须分不同组**，否则会被去重丢频道。

## 二、三层自愈机制 + 三层保障

自愈三层：
| 层级 | 谁负责 | 频率 | 电视是否要管 |
|---|---|---|---|
| 片库内容（新片/剧集） | 采集站 | 实时，现抓现播 | 不用 |
| 订阅源存活（换失效源/线路） | 本系统 GitHub Actions | 每 3 小时 | 不用 |
| App 壳版本 | 官方无自更，见第六节 | 按需 | 一年手动一两次 |

新增三层保障（v2）：
- **健康判定加固**：每源重复探测 2 次 + 延迟门槛 + 站点数基线（低于上次一半判失效），慢源偶发成功不再误判。
- **原子写入 + 分组回填**：config/state/report 用 tmp+fsync+os.replace；点播全挂也保留上一版 subs，绝不拉空。
- **外部 watchdog**：在 GitHub 之外每 3 小时查心跳，`config.json` 超 8 小时未更新即告警并尝试恢复被禁用的 workflow。

## 三、文件清单

```
tvbox-selfheal/
├── heal.py              # 自愈核心（v2 加固版，纯标准库）
├── candidates.json      # 候选源池（已删 ghproxy、补 IPv4 直播、加自托管占位）
├── config.json          # 生成的健康配置 ← 电视端填这个的 raw 地址
├── state.json           # 运行状态（连续失败、基线、历史）
├── HEAL_REPORT.md       # 每次运行的可读报告
├── watchdog.py          # 外部心跳检测 + 自恢复（放 GitHub 之外跑）
├── _audit_evidence.md   # 实测证据（所有修订的依据）
├── .github/workflows/heal.yml  # 云端定时任务（每 3 小时）
└── README.md            # 本文件
```

## 四、部署步骤（一次性，约 10 分钟）

### 1. 建仓库（必须 Public）
在 GitHub **新建独立仓库**（不要用 fork——fork 的公开仓 scheduled workflow 默认被禁用）。**设为 Public**：私有仓 `raw.githubusercontent.com` 对电视端匿名请求返回 404，影视TV App 无法携带 token，必然拉不到配置。推的只是订阅地址，无隐私内容。

把本目录全部文件（含 `.github` 隐藏目录）传上去。

### 2. 打开 Actions 写权限
仓库 → Settings → Actions → General → Workflow permissions → 选 **Read and write permissions** → Save。

### 3. 核验 workflow 状态
```bash
gh api repos/<你的用户名>/<你的仓库>/actions/workflows/heal.yml --jq .state
# 应返回 active；返回 disabled_inactivity/disabled_fork 说明被禁用了
gh workflow run heal.yml    # 手动触发一次，确认 Actions 日志末尾 git push 成功
```

### 4. 电视端填地址（只做一次）
影视TV App → 设置 → 配置地址 → 新增，填：
```
https://raw.githubusercontent.com/<你的用户名>/<你的仓库>/main/config.json
```
国内拉取慢时改用 CDN（仅对公开仓有效）：
```
https://fastly.jsdelivr.net/gh/<你的用户名>/<你的仓库>@main/config.json
```
验证：`curl -sS -o /dev/null -w %{http_code} <上面的地址>` 必须返回 200。

### 5. APK 装到电视（一次性）
从 [FongMi/Release](https://github.com/FongMi/Release) 下 `leanback-arm64_v8a.apk`（电视版 64 位）。选包判据：`leanback`=电视版、`mobile`=手机版；`arm64_v8a`=64 位（2018 年后设备基本都是）、`armeabi_v7a`=32 位；最低 Android 7.0。先装 64 位，报「解析包出错」再换 32 位。
传输：U 盘拷贝插入安装，或手机装 `Send Files to TV` / `LocalSend` 推送。首次需在「设置→安全→允许安装未知来源」放行。
**验收**：首页出现电影/电视剧/综艺/动漫分类，搜索并播放任一影片成功。

### 6. 直播源
`config.json` 的 `lives` 默认已放 `index.m3u`（IPv4，94 频道）+ `itv.m3u`（IPv4，189 频道）+ `ipv6.m3u`（可选）。
**注意**：`fanmingming/live` 的 `tv/m3u/` 下真实只有 `index.m3u`/`itv.m3u`/`demo.m3u`/`ipv6.m3u` 四个文件，**不存在 `ipv4.m3u`，也没有 `ipv4/` 目录**。家里有 IPv6 想补频道时保留 `ipv6.m3u` 那条，否则从 `candidates.json` 删掉它再跑 `python heal.py`。

### 7. 外部 watchdog（强烈建议，防 60 天闲置禁用）
把 `watchdog.py` 放到 cron-job.org / 腾讯云 SCF，每 3 小时跑一次：
```bash
python watchdog.py \
  --config-url https://raw.githubusercontent.com/<user>/<repo>/main/config.json \
  --repo <user>/<repo> \
  --workflow heal.yml \
  --bark-key <你的Bark Key> \
  --enable-key <你的GitHub Token>
```
github token 需要 repo 写权限，用于 workflow 被禁用时自动 `gh workflow enable`。没有 token 时至少能告警。

## 五、日常使用（你什么都不用做）

| 故障 | 系统反应 |
|---|---|
| 主 m.json 打不开 | 3 小时内自动切 jsdelivr CDN → 再挂切 ghpages 镜像 |
| 某点播源偶发超时 | 重复探测 2 次 + 延迟门槛，不会被误判健康 |
| 点播源全挂、直播正常 | **保留上一版 subs**，电视点播不拉空（v2 修复） |
| 全部源失效 | 保留上一版完整配置；连续 3 轮在报告顶部红色告警 |
| workflow 被禁用/停摆 | 外部 watchdog 检测心跳超时、告警并尝试自恢复 |
| 采集站上新片 | 采集站实时更新，电视现抓现播 |
| 想立刻刷新 | Actions 页 Run workflow，或 `gh workflow run heal.yml` |

本地故障注入切换约几秒；云端由 cron 决定，最坏间隔 3 小时。

## 六、自定义候选源

编辑 `candidates.json`：
```json
{"id":"唯一标识","name":"显示名","kind":"json 或 m3u","url":"订阅地址",
 "priority":1,"failover_group":"同组名","timeout_seconds":8,"enabled":true}
```
- `priority`：越小越优先。
- `failover_group`：**VOD 同内容镜像必须填同一组名**（每组只取一个，避免 234×3 重复站点）；**live 不同频道集必须填不同组名**（否则去重会丢频道）。
- `kind: json` 要求含 `sites` 数组且有效站点数 ≥ `min_sites`（并做基线校验）；`kind: m3u` 要求 `#EXTM3U` 头且频道数 ≥ `min_channels`（40）。
- `timeout_seconds`：单源超时，可覆盖全局 `timeout_seconds`（12）。慢源设 8 快速失败。
- `enabled: false`：临时停用某源（未配置的自托管快照默认 false）。

**抗整仓停更的兜底（已部署上线）**：三个公共点播入口全是 `liu673cn/box` 同一份 m.json 的镜像，该仓整体停更/被封时三条同时失效。已上线独立 Public 仓库 **`https://github.com/ByShiNo/tvbox-mirror`**：`snapshot.py` 每 6 小时把 m.json 抓到该仓 `mirror/` 目录，校验 sites≥10 且不低于基线一半才覆盖，保留 last good、原子写；workflow `snapshot.yml` 状态 active，Actions 为读写权限。`candidates.json` 的 `selfhost-snapshot` 已 `enabled:true`、`priority:4`、url 指向 `https://raw.githubusercontent.com/ByShiNo/tvbox-mirror/main/mirror/m.json`（实测 HTTP 200 / 85994B）。上游整仓停更时 heal.py 自动切到这份快照。

## 七、已实测失效源（勿添加，2026-11-23 复测）

| URL | 状态 |
|---|---|
| `https://raw.githubusercontent.com/leevi0909/TVBox/main/jsm.json` | 404 |
| `https://raw.githubusercontent.com/uzshare/uzbox/main/config.json` | 404 |
| `https://jihulab.com/yingshicang/yingshicang/-/raw/main/yingshicang.json` | 401 需登录 |
| `https://gitlab.com/yingshicang/yingshicang/-/raw/main/yingshicang.json` | 404 |
| `https://raw.kkgithub.com/leevi0909/TVBox/main/jsm.json` | 证书过期 |
| `https://raw.githubusercontent.com/liu673cn/box/main/jsm.json` | 404（只有 m.json） |
| `https://raw.githubusercontent.com/takagen99/Box/main/config.json` | 404 |
| `https://ghproxy.net/https://raw.githubusercontent.com/liu673cn/box/main/m.json` | >12s 超时，不纳入自动切换 |

## 八、App 版本更新（三档）

查证（2026-11-23）：FongMi/Release 最新 **5.9.0**（2026-11-22）。官方 App 无内置自更新，但**版本与片源无关**，旧版照样加载订阅。

| 档位 | 做法 | 无人值守 |
|---|---|---|
| 省事档 | 影视仓等带「在线更新」选项的分支，遥控确认 | 半自动 |
| 无人值守档 | 定时请求 `https://api.github.com/repos/FongMi/Release/releases/latest`，取 `assets[].browser_download_url` 含 `leanback-arm64_v8a.apk`，下载后调用系统安装器（需未知来源 + 无障碍或 ADB 安装权限） | 全自动 |
| 现实档（推荐） | 不折腾，一年手动升一两次即可 | 最稳 |

latest 直链：`https://github.com/FongMi/Release/releases/latest/download/leanback-arm64_v8a.apk`

## 九、残留风险（机制上无法根除）

1. **点播内容源单一**：所有公共点播源都是 `liu673cn/box` 一个仓的镜像，实测无第二家可用公共仓（takagen99/mengtemps/xyqyear 全 404）。**已通过 `tvbox-mirror` 自托管快照兜底**（见第六节/独立仓库）：上游整仓停更时自动切到你自己的快照，片库是最后一版合格数据；快照本身也受 last good 保护。部署后此风险闭环。
2. **GitHub 平台依赖**：schedule 高峰期有数十分钟延迟；公开仓 60 天闲置会被禁用（靠 watchdog 补救）；私有仓电视拉不到（必须 Public）。
3. **采集站本身**：片源来自第三方采集站，采集站关停会减少源，这是对上游的固有依赖，脚本只能切换订阅不能修采集站。
4. **电视端网络**：国内 raw 拉取可能不稳定，用 CDN 镜像；IPv6 直播需电视/宽带支持 IPv6。

## 十、本地测试

```bash
python heal.py           # 立即探测并生成配置
cat HEAL_REPORT.md       # 看探测报告
# 故障注入：把 candidates.json 某源 url 改成 404 再跑 python heal.py，看切换与兜底
```

已验证场景：主源 404→切 CDN；点播单独全挂→保留 subs（v2 修复）；全部失效→保留上一版+告警；源恢复→切回主源。

## 参考来源
- [FongMi/TV GitHub](https://github.com/FongMi/TV)
- [影视TV 官方文档](https://fongmi.github.io/TV/)
- [影视TV 使用详解](https://shaun.top/archives/ying-shi-tv-fongmi-tv)
