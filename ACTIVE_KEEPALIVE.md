# A 方案：纯 GitHub 保活说明（零外部依赖）

## 结论

这套系统**只需要 GitHub 自己就能一直活着**，不用腾讯云、不用任何第三方。原因：GitHub 会禁用 scheduled workflow 的唯一条件是「仓库连续 60 天无任何活动」，而我们的自愈 workflow 每 3 小时都会产生一次 commit，仓库永远活跃，这条规则永远不触发。

## 为什么仓库永远活跃

看 workflow 的提交步骤（`.github/workflows/heal.yml`）：

```yaml
git add config.json state.json HEAL_REPORT.md
if git diff --cached --quiet; then
  echo "无变化，跳过提交"
else
  git commit -m "chore: 自愈更新配置 ..."
  git push ...
fi
```

关键点：**`state.json` 每轮都写**。heal.py 每次运行都更新 `state.json` 的 `last_run` 和 `history`（见 heal.py 第 421-430 行），即使 config.json 的源列表没变化，state.json 也变了 → `git diff --cached` 不为空 → 每轮都 commit + push。

## 线上实测证据（2026-11-23）

```
state.json last_run = 2026-11-23 20:54:20 +0800（每轮刷新）
commit 历史：
  12:54:20  chore: 自愈更新配置 2026-11-23T12:54:20Z
  ...
```

每 3 小时一条 `chore: 自愈更新配置` commit，仓库持续活跃。

## 三层存活逻辑

| 层 | 谁维护 | 频率 | 停摆风险 |
|---|---|---|---|
| 片源实时 | 采集站 | 实时 | 上游挂了 → 云端自愈切源 |
| 配置自愈 | GitHub Actions (heal.yml) | 每 3h | 靠自身 commit 保活，60天规则不触发 |
| Actions 自愈 | B 方案互监控仓 / SCF watchdog | 每 3h | 保险中的保险，可选 |

## 要做的事

**无。** A 方案不需要你做任何部署，当前就是可用状态。

## 什么情况下才需要 B 或 SCF

- GitHub 官方改变了闲置判定规则
- workflow 因代码错误连续失败被平台自动禁用
- 你想在停摆时收到手机告警（B 方案默认只在仓库内记录，SCF 能推 Bark/微信）

正常家用场景，A 方案足够。
