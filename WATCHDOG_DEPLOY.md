# Watchdog 云端部署手册（腾讯云 SCF 定时触发）

> 目的：GitHub 公开仓闲置 60 天会禁用 schedule 且不自恢复。外部 watchdog 每 3 小时探一次心跳，停了就告警 + 自动重新启用并补跑 workflow。做到真正无人值守。

## 关键修正（2026-11-23 实测得出）

**config.json 不能当心跳！** 它的 `_meta.updated` 只在源列表**变化时**才更新；健康运行时 heal.py 检测到"无变化"就不写盘，config.json 停在最后切源时间。拿它当心跳会在健康状态下误报停摆。

可靠心跳源（watchdog.py 已按此优先级实现）：
1. **GitHub Actions API** —— 最近一次 workflow run 时间，最真实（`--repo` + `--token` 启用）
2. **state.json 的 `last_run`** —— heal.py 每轮都写，公开 raw 匿名可读（推荐无 token 场景）
3. config.json 的 `_meta.updated` —— 仅兜底参考

## 本地实测结果（已验证）

```
心跳源=state.json         | 2026-11-23 19:23:13 +0800 | 年龄=1.5h | 心跳正常
心跳源=GitHub Actions API | 2026-11-23T11:23:04Z      | 年龄=1.5h | completed/success | 心跳正常
```

## 方案 A：腾讯云 SCF（推荐，免费额度够用）

### 1. 准备文件
把这两个文件放进同一个目录打成 zip：
- `scf_handler.py`（入口）
- `watchdog.py`（核心逻辑）

### 2. 建函数
- 控制台 → 云函数 SCF → 新建 → 函数类型「函数」→ 运行环境 Python 3.9+
- 函数名称：`tvbox-watchdog`
- 上传方式：本地上传 zip
- 执行入口：`scf_handler.main_handler`
- 超时时间：60 秒；内存 128MB 即可

### 3. 配环境变量（函数配置 → 环境变量）
| 变量 | 值 | 说明 |
|---|---|---|
| `REPO` | `ByShiNo/tvbox-selfheal` | 被监控的仓 |
| `WORKFLOW` | `heal.yml` | 被监控的 workflow |
| `STATE_URL` | `https://raw.githubusercontent.com/ByShiNo/tvbox-selfheal/main/state.json` | 无 token 时的心跳源 |
| `CONFIG_URL` | `https://raw.githubusercontent.com/ByShiNo/tvbox-selfheal/main/config.json` | 兜底 |
| `GH_TOKEN` | `<你的 GitHub PAT>` | 可选但推荐，用于读 Actions API + 自恢复 |
| `BARK_KEY` | `<Bark Key>` | 可选，告警推送 |
| `SERVERCHAN_KEY` | `<Server酱 key>` | 可选，告警推送 |
| `MAX_AGE_HOURS` | `8` | 心跳阈值，超过即告警 |

### 4. GitHub PAT 权限（若要自恢复）
GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token：
- 勾 `repo`（读 state.json 私有场景）+ `actions:write` 或 `workflow`（重新启用/触发 workflow）
- 过期选"永不"或尽量长
- 把 token 填进 `GH_TOKEN` 环境变量

> 自恢复动作 = `PUT /repos/{repo}/actions/workflows/{wf}/enable` + `POST .../dispatches`。这两个 API 用 `actions:write` 权限的 PAT 即可，**不需要 workflow scope 去 push 代码**（绕开了之前 git push 的坑）。

### 5. 设定时触发器
SCF 函数 → 触发管理 → 创建触发器 → 定时触发：
- Cron 表达式：`0 0 */3 * * * *`（每 3 小时整点，SCF 是 7 位 cron：秒 分 时 日 月 周 年）
- 或直接 `0 0 */3 * * * *` 表示每天 0/3/6/9/12/15/18/21 点触发

### 6. 验证
- SCF 控制台 → 测试 → 点"测试"，看日志输出「心跳正常」
- 故意把 `MAX_AGE_HOURS` 设成 `0` 测试告警分支（会推 Bark + 触发 workflow），测完改回 8

## 方案 B：cron-job.org（无 SCF，最简单）

如果只想要"告警 + 手动恢复"，不追求自动 enable：
- 注册 cron-job.org（免费）
- 新建任务，URL 填一个能跑到 watchdog 的 HTTP 端点（需要你有个能执行 Python 的地方，比如已有的云函数/NAAS）
- 若用 GitHub Actions 自己当触发器则违反"心跳在 GitHub 之外"原则，故 SCF 方案 A 更彻底

## 告警渠道配置

- **Bark（iOS）**：App 装 Bark → 复制推送 URL 里的 key → 填 `BARK_KEY`
- **Server酱（微信）**：https://sc.ftqq.com 注册拿 SendKey → 填 `SERVERCHAN_KEY`
- 两者都不填：只在 SCF 日志里打印告警

## 自恢复链路（停摆时自动发生）

```
SCF 每3h 读 Actions API 心跳
  → 年龄 > 8h（疑似停用/停摆）
  → 推 Bark/Server酱 告警
  → PUT .../workflows/heal.yml/enable    （重新启用被禁用的 workflow）
  → POST .../workflows/heal.yml/dispatches（补跑一次）
  → 电视端 config.json 恢复新鲜
```

## 边界说明

- SCF 免费额度：每月 100 万次调用 + 120 万 GB·s，每 3h 一次一个月才 ~240 次，完全免费。
- 若 GitHub PAT 过期，自恢复会失败但**告警仍会发出**（watchdog 不依赖 token 也能读公开 state.json）。
- 这是整条链的最后一块拼图：片源实时 ← 采集站；配置自愈 ← GitHub Actions；Actions 自愈 ← 本 watchdog。三层都无人值守。
